"""Reading candidate variants' genotypes from a VCF file or a table."""
import csv
import gzip
import io
from collections import Counter
from typing import Dict, Iterable, List, Optional

from .segregation import Variant


def _open_text(path):
    """A plain or gzipped text file, read as UTF-8 with or without the byte-order mark Excel writes"""
    with open(path, 'rb') as handle:
        magic = handle.read(2)
    if magic == b'\x1f\x8b':
        return io.TextIOWrapper(gzip.open(path), encoding='utf-8-sig')
    return open(path, encoding='utf-8-sig')


def _unique_ids(variants: List[Variant]) -> List[Variant]:
    """
    Makes every variant's ID its own. An ID shared by several variants, as when bcftools norm -m- splits a site with
    two alternate alleles and keeps its rsID on both, has the variant's place added (rs9 1:100:A>T), or failing that
    a number
    """
    counts = Counter(v.id for v in variants)
    seen: Counter = Counter()
    for v in variants:
        if counts[v.id] > 1:
            if v.chrom is not None and v.pos is not None:
                v.id = f'{v.id} {v.chrom}:{v.pos}:{v.ref}>{v.alt}'
            else:
                seen[v.id] += 1
                v.id = f'{v.id} ({seen[v.id]})'
    if len({v.id for v in variants}) < len(variants):
        seen = Counter()
        for v in variants:
            seen[v.id] += 1
            if seen[v.id] > 1:
                v.id = f'{v.id} ({seen[v.id]})'
    return variants


def _copies(call: str, allele: int = 1) -> Optional[int]:
    """The number of copies of an allele in a genotype call such as 0/1, 1|1, 1 or ./. (None if missing)"""
    call = call.strip()
    if call in ('', '.', 'NA', 'nan'):
        return None
    alleles = call.replace('|', '/').split('/')
    if any(a in ('.', '') for a in alleles):
        return None
    try:
        return sum(int(a) == allele for a in alleles)
    except ValueError:
        return None


_COUNTS = {'0': 0, '1': 1, '2': 2, '0.0': 0, '1.0': 1, '2.0': 2}


def _table_genotype(value: str, where: str = '') -> Optional[int]:
    """
    A genotype in a table: a count of alternate alleles (0, 1 or 2, or 0.0, 1.0 or 2.0) or a call such as 0/1 or 1|1,
    with '', '.', 'NA' and ./. for no call. Anything else is an error, named by where.
    """
    value = str(value).strip()
    if value in ('', '.', 'NA', 'nan', './.', '.|.', '-'):
        return None
    if value in _COUNTS:
        return _COUNTS[value]
    alleles = value.replace('|', '/').split('/')
    if len(alleles) == 2 and all(a.isdigit() for a in alleles):
        return sum(a != '0' for a in alleles)
    if len(alleles) == 2 and all(a == '.' or a.isdigit() for a in alleles):
        return None
    raise ValueError(f'{where}{" " if where else ""}has the genotype {value!r}, which isn\'t 0, 1 or 2 copies or a '
                     'call such as 0/1')


def _frequency(value: Optional[str], where: str) -> Optional[float]:
    if value is None or value.strip().lower() in ('', '.', 'na', 'nan', '-'):
        return None
    try:
        frequency = float(value)
    except ValueError:
        raise ValueError(f'{where} has the allele frequency {value!r}, which isn\'t a number') from None
    if not 0 <= frequency <= 1:
        raise ValueError(f'{where} has the allele frequency {value!r}, which isn\'t between 0 and 1')
    return frequency


# INFO fields that may name a variant's gene, in the order they are looked for: those of VEP, SnpEff and bcftools csq,
# then single fields, as from ANNOVAR or dbSNP
GENE_KEYS = ('CSQ', 'ANN', 'BCSQ', 'GENE', 'SYMBOL', 'Gene.refGene', 'Gene.ensGene', 'GENEINFO')


def read_vcf(path, samples: Optional[Iterable[str]] = None, frequency_key: str = 'AF',
             passed_only: bool = False, gene_key: Optional[str] = None) -> List[Variant]:
    """
    Reads candidate variants from a VCF file (plain or gzipped). Each alternate allele of a site becomes a variant
    of its own, with each sample's number of copies of it from the GT field. The allele frequency is taken from
    the INFO field frequency_key (AF by default; for example gnomAD's AF_joint, if the VCF was annotated with it).

    samples: keep only these samples (for example the people in a pedigree)
    passed_only: keep only sites whose FILTER is PASS or '.'
    gene_key: the INFO field naming the gene, which pairs variants up as compound heterozygotes. By default the
        first of GENE_KEYS present: VEP's CSQ (its SYMBOL), SnpEff's ANN, bcftools csq's BCSQ, or a field such as
        GENE, Gene.refGene (ANNOVAR) or GENEINFO (dbSNP)
    """
    wanted = set(samples) if samples is not None else None
    variants: List[Variant] = []
    names: List[str] = []
    csq_fields: List[str] = []
    with _open_text(path) as handle:
        for line in handle:
            if line.startswith('##'):
                if line.startswith('##INFO=<ID=CSQ,') and 'Format:' in line:
                    csq_fields = line.split('Format:', 1)[1].strip().rstrip('">').strip().split('|')
                continue
            if line.startswith('#'):
                names = line.rstrip('\n\r').split('\t')[9:]
                continue
            fields = line.rstrip('\n\r').split('\t')
            if len(fields) < 8:
                continue
            chrom, pos, vid, ref, alts, _, filt, info = fields[:8]
            if passed_only and filt not in ('PASS', '.'):
                continue
            fmt = fields[8].split(':') if len(fields) > 8 else []
            gt = fmt.index('GT') if 'GT' in fmt else None
            frequencies = _info_values(info, frequency_key)
            items = _info_items(info)
            alt_list = alts.split(',')
            for a, alt in enumerate(alt_list, start=1):
                if alt in ('.', '*'):
                    continue
                genotypes: Dict[str, Optional[int]] = {}
                if gt is not None:
                    for name, sample in zip(names, fields[9:]):
                        if wanted is not None and name not in wanted:
                            continue
                        parts = sample.split(':')
                        genotypes[name] = _copies(parts[gt], a) if gt < len(parts) else None
                if vid not in ('.', '') and len(alt_list) == 1:
                    identifier = vid
                else:
                    identifier = f'{chrom}:{pos}:{ref}>{alt}'
                frequency = frequencies[a - 1] if len(frequencies) >= a else None
                gene = _gene(items, alt, len(alt_list), gene_key, csq_fields)
                variants.append(Variant(identifier, genotypes, chrom, int(pos), ref, alt, frequency, gene))
    return _unique_ids(variants)


def vcf_samples(path) -> List[str]:
    """The names of a VCF file's samples, from its header"""
    with _open_text(path) as handle:
        for line in handle:
            if line.startswith('#CHROM'):
                return line.rstrip('\n\r').split('\t')[9:]
            if not line.startswith('#'):
                break
    return []


def _info_items(info: str) -> Dict[str, str]:
    items = {}
    for item in info.split(';'):
        key, _, value = item.partition('=')
        items.setdefault(key, value)
    return items


def _gene(items: Dict[str, str], alt: str, n_alts: int, key: Optional[str], csq_fields: List[str]) -> Optional[str]:
    """The gene an alternate allele is in, from the INFO field key (or the first of GENE_KEYS present)"""
    for k in ([key] if key else GENE_KEYS):
        value = items.get(k)
        if not value or value == '.':
            continue
        if k in ('CSQ', 'ANN', 'BCSQ'):
            if k == 'CSQ':
                position = csq_fields.index('SYMBOL') if 'SYMBOL' in csq_fields else 3
            else:
                position = 3 if k == 'ANN' else 1
            matched, others = None, None
            for annotation in value.split(','):
                parts = annotation.split('|')
                if len(parts) <= position or parts[position] in ('', '.'):
                    continue
                # an annotation of this allele (ANN and CSQ start with it), or else any
                if k != 'BCSQ' and n_alts > 1 and parts[0] == alt:
                    matched = matched or parts[position]
                others = others or parts[position]
            gene = matched or others
        elif k == 'GENEINFO':
            gene = value.split('|')[0].split(':')[0]
        else:
            gene = value.replace('\\x3b', ',').replace('\\x3B', ',').split(',')[0]
        if gene and gene != '.':
            return gene
    return None


def _info_values(info: str, key: str) -> List[Optional[float]]:
    for item in info.split(';'):
        if item.startswith(key + '='):
            out = []
            for value in item[len(key) + 1:].split(','):
                try:
                    out.append(float(value))
                except ValueError:
                    out.append(None)
            return out
    return []


def read_genotype_table(path, delimiter: Optional[str] = None) -> List[Variant]:
    """
    Reads candidate variants from a table with one row per variant: a column variant (or id) naming it, optional
    columns chrom, pos, ref, alt, af (its allele frequency) and gene, and a column for each person, holding the number
    of copies of the alternate allele (0, 1 or 2) or a call such as 0/1. Empty cells and ./. mean not genotyped.
    The columns are separated by tabs, unless the file ends in .csv or delimiter says otherwise.
    """
    if delimiter is None:
        delimiter = ',' if str(path).lower().endswith('.csv') else '\t'
    known = {'variant', 'id', 'chrom', 'chr', 'chromosome', 'pos', 'position', 'ref', 'alt', 'af', 'allele_frequency',
             'gene', 'symbol'}
    variants = []
    with _open_text(path) as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if reader.fieldnames is None:
            return []
        lower = {name: name.strip().lower() for name in reader.fieldnames}
        people = [name for name in reader.fieldnames if lower[name] not in known]
        def column(row, *keys):
            for name in reader.fieldnames:
                if lower[name] in keys and row.get(name) not in (None, ''):
                    return row[name].strip()
            return None
        for number, row in enumerate(reader, start=1):
            identifier = column(row, 'variant', 'id') or f'variant {number}'
            where = f'Row {number} ({identifier})'
            pos = column(row, 'pos', 'position')
            try:
                position = int(pos) if pos else None
            except ValueError:
                raise ValueError(f'{where} has the position {pos!r}, which isn\'t a whole number') from None
            genotypes = {p.strip(): _table_genotype(row[p] if row[p] is not None else '', f'{where}, column {p},')
                         for p in people}
            variants.append(Variant(identifier, genotypes, column(row, 'chrom', 'chr', 'chromosome'), position,
                                    column(row, 'ref'), column(row, 'alt'),
                                    _frequency(column(row, 'af', 'allele_frequency'), where),
                                    column(row, 'gene', 'symbol')))
    return _unique_ids(variants)
