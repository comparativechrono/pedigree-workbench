"""The shape of every message this package reads and writes.

``MESSAGES`` lists the fields of each Phenopacket schema v2 message, taken
from the ``.proto`` files of phenopacket-schema 2.0, plus the two messages of
the GA4GH Pedigree in its Phenopackets form (``GA4GHPedigree`` and
``Relationship``). Each field has its JSON name (lowerCamelCase), its proto
name (snake_case) and its type.

``REQUIRED`` and the other constraints follow the JSON schemas that
phenopacket-tools, the Phenopackets team's validator, applies to Phenopackets v2.
For the GA4GH Pedigree they follow the field multiplicities of the standard's
conceptual model and the proposed ``pedigree.proto``.

proto3 JSON: writers use the lowerCamelCase names; readers must accept both
those and the original proto names, so ``vital_status`` and ``vitalStatus``
mean the same field (see :func:`camelise`). Fields holding a type's default
value (an empty string, ``false``, ``0``, the first enum value) may be left out.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple


@dataclass(frozen=True)
class F:
    json: str                 # JSON name, e.g. "vitalStatus"
    proto: str                # proto name, e.g. "vital_status"
    type: str                 # "string", "bool", "int32", "uint32", "uint64", "double",
                              # "timestamp", "map", "opaque", "enum:<Enum>" or a message name
    repeated: bool = False
    oneof: Optional[str] = None


MESSAGES = {
    'OntologyClass': [
        F('id', 'id', 'string'),
        F('label', 'label', 'string'),
    ],
    'ExternalReference': [
        F('id', 'id', 'string'),
        F('reference', 'reference', 'string'),
        F('description', 'description', 'string'),
    ],
    'Evidence': [
        F('evidenceCode', 'evidence_code', 'OntologyClass'),
        F('reference', 'reference', 'ExternalReference'),
    ],
    'Procedure': [
        F('code', 'code', 'OntologyClass'),
        F('bodySite', 'body_site', 'OntologyClass'),
        F('performed', 'performed', 'TimeElement'),
    ],
    'GestationalAge': [
        F('weeks', 'weeks', 'int32'),
        F('days', 'days', 'int32'),
    ],
    'Age': [
        F('iso8601duration', 'iso8601duration', 'string'),
    ],
    'AgeRange': [
        F('start', 'start', 'Age'),
        F('end', 'end', 'Age'),
    ],
    'TimeInterval': [
        F('start', 'start', 'timestamp'),
        F('end', 'end', 'timestamp'),
    ],
    'TimeElement': [
        F('gestationalAge', 'gestational_age', 'GestationalAge', oneof='element'),
        F('age', 'age', 'Age', oneof='element'),
        F('ageRange', 'age_range', 'AgeRange', oneof='element'),
        F('ontologyClass', 'ontology_class', 'OntologyClass', oneof='element'),
        F('timestamp', 'timestamp', 'timestamp', oneof='element'),
        F('interval', 'interval', 'TimeInterval', oneof='element'),
    ],
    'File': [
        F('uri', 'uri', 'string'),
        F('individualToFileIdentifiers', 'individual_to_file_identifiers', 'map'),
        F('fileAttributes', 'file_attributes', 'map'),
    ],
    'Biosample': [
        F('id', 'id', 'string'),
        F('individualId', 'individual_id', 'string'),
        F('derivedFromId', 'derived_from_id', 'string'),
        F('description', 'description', 'string'),
        F('sampledTissue', 'sampled_tissue', 'OntologyClass'),
        F('sampleType', 'sample_type', 'OntologyClass'),
        F('phenotypicFeatures', 'phenotypic_features', 'PhenotypicFeature', repeated=True),
        F('measurements', 'measurements', 'Measurement', repeated=True),
        F('taxonomy', 'taxonomy', 'OntologyClass'),
        F('timeOfCollection', 'time_of_collection', 'TimeElement'),
        F('histologicalDiagnosis', 'histological_diagnosis', 'OntologyClass'),
        F('tumorProgression', 'tumor_progression', 'OntologyClass'),
        F('tumorGrade', 'tumor_grade', 'OntologyClass'),
        F('pathologicalStage', 'pathological_stage', 'OntologyClass'),
        F('pathologicalTnmFinding', 'pathological_tnm_finding', 'OntologyClass', repeated=True),
        F('diagnosticMarkers', 'diagnostic_markers', 'OntologyClass', repeated=True),
        F('procedure', 'procedure', 'Procedure'),
        F('files', 'files', 'File', repeated=True),
        F('materialSample', 'material_sample', 'OntologyClass'),
        F('sampleProcessing', 'sample_processing', 'OntologyClass'),
        F('sampleStorage', 'sample_storage', 'OntologyClass'),
    ],
    'Disease': [
        F('term', 'term', 'OntologyClass'),
        F('excluded', 'excluded', 'bool'),
        F('onset', 'onset', 'TimeElement'),
        F('resolution', 'resolution', 'TimeElement'),
        F('diseaseStage', 'disease_stage', 'OntologyClass', repeated=True),
        F('clinicalTnmFinding', 'clinical_tnm_finding', 'OntologyClass', repeated=True),
        F('primarySite', 'primary_site', 'OntologyClass'),
        F('laterality', 'laterality', 'OntologyClass'),
    ],
    'Individual': [
        F('id', 'id', 'string'),
        F('alternateIds', 'alternate_ids', 'string', repeated=True),
        F('dateOfBirth', 'date_of_birth', 'timestamp'),
        F('timeAtLastEncounter', 'time_at_last_encounter', 'TimeElement'),
        F('vitalStatus', 'vital_status', 'VitalStatus'),
        F('sex', 'sex', 'enum:Sex'),
        F('karyotypicSex', 'karyotypic_sex', 'enum:KaryotypicSex'),
        F('gender', 'gender', 'OntologyClass'),
        F('taxonomy', 'taxonomy', 'OntologyClass'),
    ],
    'VitalStatus': [
        F('status', 'status', 'enum:VitalStatus.Status'),
        F('timeOfDeath', 'time_of_death', 'TimeElement'),
        F('causeOfDeath', 'cause_of_death', 'OntologyClass'),
        F('survivalTimeInDays', 'survival_time_in_days', 'uint32'),
    ],
    'Interpretation': [
        F('id', 'id', 'string'),
        F('progressStatus', 'progress_status', 'enum:Interpretation.ProgressStatus'),
        F('diagnosis', 'diagnosis', 'Diagnosis'),
        F('summary', 'summary', 'string'),
    ],
    'Diagnosis': [
        F('disease', 'disease', 'OntologyClass'),
        F('genomicInterpretations', 'genomic_interpretations', 'GenomicInterpretation', repeated=True),
    ],
    'GenomicInterpretation': [
        F('subjectOrBiosampleId', 'subject_or_biosample_id', 'string'),
        F('interpretationStatus', 'interpretation_status', 'enum:GenomicInterpretation.InterpretationStatus'),
        F('gene', 'gene', 'GeneDescriptor', oneof='call'),
        F('variantInterpretation', 'variant_interpretation', 'VariantInterpretation', oneof='call'),
    ],
    'VariantInterpretation': [
        F('acmgPathogenicityClassification', 'acmg_pathogenicity_classification', 'enum:AcmgPathogenicityClassification'),
        F('therapeuticActionability', 'therapeutic_actionability', 'enum:TherapeuticActionability'),
        F('variationDescriptor', 'variation_descriptor', 'VariationDescriptor'),
    ],
    'Measurement': [
        F('description', 'description', 'string'),
        F('assay', 'assay', 'OntologyClass'),
        F('value', 'value', 'Value', oneof='measurement_value'),
        F('complexValue', 'complex_value', 'ComplexValue', oneof='measurement_value'),
        F('timeObserved', 'time_observed', 'TimeElement'),
        F('procedure', 'procedure', 'Procedure'),
    ],
    'Value': [
        F('quantity', 'quantity', 'Quantity', oneof='value'),
        F('ontologyClass', 'ontology_class', 'OntologyClass', oneof='value'),
    ],
    'ComplexValue': [
        F('typedQuantities', 'typed_quantities', 'TypedQuantity', repeated=True),
    ],
    'Quantity': [
        F('unit', 'unit', 'OntologyClass'),
        F('value', 'value', 'double'),
        F('referenceRange', 'reference_range', 'ReferenceRange'),
    ],
    'TypedQuantity': [
        F('type', 'type', 'OntologyClass'),
        F('quantity', 'quantity', 'Quantity'),
    ],
    'ReferenceRange': [
        F('unit', 'unit', 'OntologyClass'),
        F('low', 'low', 'double'),
        F('high', 'high', 'double'),
    ],
    'MedicalAction': [
        F('procedure', 'procedure', 'Procedure', oneof='action'),
        F('treatment', 'treatment', 'Treatment', oneof='action'),
        F('radiationTherapy', 'radiation_therapy', 'RadiationTherapy', oneof='action'),
        F('therapeuticRegimen', 'therapeutic_regimen', 'TherapeuticRegimen', oneof='action'),
        F('treatmentTarget', 'treatment_target', 'OntologyClass'),
        F('treatmentIntent', 'treatment_intent', 'OntologyClass'),
        F('responseToTreatment', 'response_to_treatment', 'OntologyClass'),
        F('adverseEvents', 'adverse_events', 'OntologyClass', repeated=True),
        F('treatmentTerminationReason', 'treatment_termination_reason', 'OntologyClass'),
    ],
    'Treatment': [
        F('agent', 'agent', 'OntologyClass'),
        F('routeOfAdministration', 'route_of_administration', 'OntologyClass'),
        F('doseIntervals', 'dose_intervals', 'DoseInterval', repeated=True),
        F('drugType', 'drug_type', 'enum:DrugType'),
        F('cumulativeDose', 'cumulative_dose', 'Quantity'),
    ],
    'DoseInterval': [
        F('quantity', 'quantity', 'Quantity'),
        F('scheduleFrequency', 'schedule_frequency', 'OntologyClass'),
        F('interval', 'interval', 'TimeInterval'),
    ],
    'RadiationTherapy': [
        F('modality', 'modality', 'OntologyClass'),
        F('bodySite', 'body_site', 'OntologyClass'),
        F('dosage', 'dosage', 'int32'),
        F('fractions', 'fractions', 'int32'),
    ],
    'TherapeuticRegimen': [
        F('externalReference', 'external_reference', 'ExternalReference', oneof='identifier'),
        F('ontologyClass', 'ontology_class', 'OntologyClass', oneof='identifier'),
        F('startTime', 'start_time', 'TimeElement'),
        F('endTime', 'end_time', 'TimeElement'),
        F('regimenStatus', 'regimen_status', 'enum:TherapeuticRegimen.RegimenStatus'),
    ],
    'MetaData': [
        F('created', 'created', 'timestamp'),
        F('createdBy', 'created_by', 'string'),
        F('submittedBy', 'submitted_by', 'string'),
        F('resources', 'resources', 'Resource', repeated=True),
        F('updates', 'updates', 'Update', repeated=True),
        F('phenopacketSchemaVersion', 'phenopacket_schema_version', 'string'),
        F('externalReferences', 'external_references', 'ExternalReference', repeated=True),
    ],
    'Resource': [
        F('id', 'id', 'string'),
        F('name', 'name', 'string'),
        F('url', 'url', 'string'),
        F('version', 'version', 'string'),
        F('namespacePrefix', 'namespace_prefix', 'string'),
        F('iriPrefix', 'iri_prefix', 'string'),
    ],
    'Update': [
        F('timestamp', 'timestamp', 'timestamp'),
        F('updatedBy', 'updated_by', 'string'),
        F('comment', 'comment', 'string'),
    ],
    'Pedigree': [
        F('persons', 'persons', 'Person', repeated=True),
    ],
    'Person': [
        F('familyId', 'family_id', 'string'),
        F('individualId', 'individual_id', 'string'),
        F('paternalId', 'paternal_id', 'string'),
        F('maternalId', 'maternal_id', 'string'),
        F('sex', 'sex', 'enum:Sex'),
        F('affectedStatus', 'affected_status', 'enum:Pedigree.Person.AffectedStatus'),
    ],
    'PhenotypicFeature': [
        F('description', 'description', 'string'),
        F('type', 'type', 'OntologyClass'),
        F('excluded', 'excluded', 'bool'),
        F('severity', 'severity', 'OntologyClass'),
        F('modifiers', 'modifiers', 'OntologyClass', repeated=True),
        F('onset', 'onset', 'TimeElement'),
        F('resolution', 'resolution', 'TimeElement'),
        F('evidence', 'evidence', 'Evidence', repeated=True),
    ],
    'Phenopacket': [
        F('id', 'id', 'string'),
        F('subject', 'subject', 'Individual'),
        F('phenotypicFeatures', 'phenotypic_features', 'PhenotypicFeature', repeated=True),
        F('measurements', 'measurements', 'Measurement', repeated=True),
        F('biosamples', 'biosamples', 'Biosample', repeated=True),
        F('interpretations', 'interpretations', 'Interpretation', repeated=True),
        F('diseases', 'diseases', 'Disease', repeated=True),
        F('medicalActions', 'medical_actions', 'MedicalAction', repeated=True),
        F('files', 'files', 'File', repeated=True),
        F('metaData', 'meta_data', 'MetaData'),
    ],
    'Family': [
        F('id', 'id', 'string'),
        F('proband', 'proband', 'Phenopacket'),
        F('relatives', 'relatives', 'Phenopacket', repeated=True),
        F('consanguinousParents', 'consanguinous_parents', 'bool'),
        F('pedigree', 'pedigree', 'Pedigree'),
        F('files', 'files', 'File', repeated=True),
        F('metaData', 'meta_data', 'MetaData'),
    ],
    'Cohort': [
        F('id', 'id', 'string'),
        F('description', 'description', 'string'),
        F('members', 'members', 'Phenopacket', repeated=True),
        F('files', 'files', 'File', repeated=True),
        F('metaData', 'meta_data', 'MetaData'),
    ],
    'Extension': [
        F('name', 'name', 'string'),
        F('value', 'value', 'string'),
    ],
    'Expression': [
        F('syntax', 'syntax', 'string'),
        F('value', 'value', 'string'),
        F('version', 'version', 'string'),
    ],
    'VcfRecord': [
        F('genomeAssembly', 'genome_assembly', 'string'),
        F('chrom', 'chrom', 'string'),
        F('pos', 'pos', 'uint64'),
        F('id', 'id', 'string'),
        F('ref', 'ref', 'string'),
        F('alt', 'alt', 'string'),
        F('qual', 'qual', 'string'),
        F('filter', 'filter', 'string'),
        F('info', 'info', 'string'),
    ],
    'VariationDescriptor': [
        F('id', 'id', 'string'),
        F('variation', 'variation', 'opaque'),
        F('label', 'label', 'string'),
        F('description', 'description', 'string'),
        F('geneContext', 'gene_context', 'GeneDescriptor'),
        F('expressions', 'expressions', 'Expression', repeated=True),
        F('vcfRecord', 'vcf_record', 'VcfRecord'),
        F('xrefs', 'xrefs', 'string', repeated=True),
        F('alternateLabels', 'alternate_labels', 'string', repeated=True),
        F('extensions', 'extensions', 'Extension', repeated=True),
        F('moleculeContext', 'molecule_context', 'enum:MoleculeContext'),
        F('structuralType', 'structural_type', 'OntologyClass'),
        F('vrsRefAlleleSeq', 'vrs_ref_allele_seq', 'string'),
        F('allelicState', 'allelic_state', 'OntologyClass'),
    ],
    'GeneDescriptor': [
        F('valueId', 'value_id', 'string'),
        F('symbol', 'symbol', 'string'),
        F('description', 'description', 'string'),
        F('alternateIds', 'alternate_ids', 'string', repeated=True),
        F('alternateSymbols', 'alternate_symbols', 'string', repeated=True),
        F('xrefs', 'xrefs', 'string', repeated=True),
    ],
}
ENUMS = {
    'VitalStatus.Status': ('UNKNOWN_STATUS', 'ALIVE', 'DECEASED'),
    'Sex': ('UNKNOWN_SEX', 'FEMALE', 'MALE', 'OTHER_SEX'),
    'KaryotypicSex': ('UNKNOWN_KARYOTYPE', 'XX', 'XY', 'XO', 'XXY', 'XXX', 'XXYY', 'XXXY', 'XXXX', 'XYY', 'OTHER_KARYOTYPE'),
    'Interpretation.ProgressStatus': ('UNKNOWN_PROGRESS', 'IN_PROGRESS', 'COMPLETED', 'SOLVED', 'UNSOLVED'),
    'GenomicInterpretation.InterpretationStatus': ('UNKNOWN_STATUS', 'REJECTED', 'CANDIDATE', 'CONTRIBUTORY', 'CAUSATIVE'),
    'AcmgPathogenicityClassification': ('NOT_PROVIDED', 'BENIGN', 'LIKELY_BENIGN', 'UNCERTAIN_SIGNIFICANCE', 'LIKELY_PATHOGENIC', 'PATHOGENIC'),
    'TherapeuticActionability': ('UNKNOWN_ACTIONABILITY', 'NOT_ACTIONABLE', 'ACTIONABLE'),
    'DrugType': ('UNKNOWN_DRUG_TYPE', 'PRESCRIPTION', 'EHR_MEDICATION_LIST', 'ADMINISTRATION_RELATED_TO_PROCEDURE'),
    'TherapeuticRegimen.RegimenStatus': ('UNKNOWN_STATUS', 'STARTED', 'COMPLETED', 'DISCONTINUED'),
    'Pedigree.Person.AffectedStatus': ('MISSING', 'UNAFFECTED', 'AFFECTED'),
    'MoleculeContext': ('unspecified_molecule_context', 'genomic', 'transcript', 'protein'),
}

# The GA4GH Pedigree, Phenopackets form: org.ga4gh.pedigree.v1 as proposed in
# phenopacket-schema pull request #364 and used by the standard's examples.
MESSAGES["GA4GHPedigree"] = [
    F("id", "id", "string"),
    F("narrative", "narrative", "string"),
    F("date", "date", "string"),
    F("status", "status", "string"),
    F("indexPatients", "index_patients", "string", repeated=True),
    F("individuals", "individuals", "Phenopacket", repeated=True),
    F("relationships", "relationships", "Relationship", repeated=True),
]
MESSAGES["Relationship"] = [
    F("individualId", "individual_id", "string"),
    F("relation", "relation", "OntologyClass"),
    F("relativeId", "relative_id", "string"),
]

# Fields that must be present. As in proto3 JSON, an enum or bool field that is
# left out holds its default value, so those count as present.
REQUIRED: Dict[str, Tuple[str, ...]] = {
    "Phenopacket": ("id", "metaData"),
    "Family": ("id", "proband", "consanguinousParents", "pedigree", "metaData"),
    "Cohort": ("id", "members", "metaData"),
    "Individual": ("id",),
    "VitalStatus": ("status",),
    "MetaData": ("created", "createdBy", "phenopacketSchemaVersion"),
    "Resource": ("id", "name", "url", "version", "namespacePrefix", "iriPrefix"),
    "Update": ("timestamp",),
    "OntologyClass": ("id", "label"),
    "Evidence": ("evidenceCode",),
    "Procedure": ("code",),
    "GestationalAge": ("weeks",),
    "Age": ("iso8601duration",),
    "AgeRange": ("start", "end"),
    "TimeInterval": ("start", "end"),
    "File": ("uri",),
    "Biosample": ("id",),
    "Disease": ("term",),
    "PhenotypicFeature": ("type",),
    "Interpretation": ("id", "progressStatus"),
    "Diagnosis": ("disease",),
    "GenomicInterpretation": ("subjectOrBiosampleId", "interpretationStatus"),
    "GeneDescriptor": ("valueId", "symbol"),
    "VariantInterpretation": ("acmgPathogenicityClassification", "therapeuticActionability",
                              "variationDescriptor"),
    "Measurement": ("assay",),
    "ComplexValue": ("typedQuantities",),
    "Quantity": ("unit", "value"),
    "TypedQuantity": ("type", "quantity"),
    "ReferenceRange": ("unit", "low", "high"),
    "Treatment": ("agent",),
    "DoseInterval": ("quantity", "scheduleFrequency", "interval"),
    "RadiationTherapy": ("modality", "bodySite", "dosage", "fractions"),
    "TherapeuticRegimen": ("regimenStatus",),
    "Pedigree": ("persons",),
    "Person": ("familyId", "individualId", "paternalId", "maternalId", "sex", "affectedStatus"),
    "GA4GHPedigree": ("id",),
    "Relationship": ("individualId", "relation", "relativeId"),
}

# Lists that must not be empty when given.
MIN_ITEMS: Dict[Tuple[str, str], int] = {
    ("MetaData", "resources"): 1,
    ("Pedigree", "persons"): 1,
    ("Cohort", "members"): 1,
    ("ComplexValue", "typedQuantities"): 1,
}

# Messages in which exactly one member of a oneof must be set.
ONEOF_REQUIRED: Dict[str, str] = {
    "TimeElement": "element",
    "Value": "value",
    "Measurement": "measurement_value",
    "MedicalAction": "action",
    "GenomicInterpretation": "call",
    "TherapeuticRegimen": "identifier",
}

_BY_JSON: Dict[str, Dict[str, F]] = {m: {f.json: f for f in fs} for m, fs in MESSAGES.items()}
_BY_PROTO: Dict[str, Dict[str, F]] = {m: {f.proto: f for f in fs} for m, fs in MESSAGES.items()}


def fields(message: str) -> Dict[str, F]:
    """JSON name -> field, for one message."""
    return _BY_JSON[message]


def field(message: str, key: str) -> Optional[F]:
    """Look a key up by its JSON name or its proto name."""
    return _BY_JSON[message].get(key) or _BY_PROTO[message].get(key)


def is_message(type_name: str) -> bool:
    return type_name in MESSAGES


def enum_values(type_name: str) -> Tuple[str, ...]:
    return ENUMS[type_name[len("enum:"):]]


def camelise(obj, message: str, path: str = "", renamed: Optional[List[str]] = None):
    """Return a copy of ``obj`` with proto (snake_case) field names in JSON form.

    Only the field names of known messages are changed; the keys of map fields
    (``fileAttributes``, ``individualToFileIdentifiers``) and of unknown fields
    are left alone. Each rename is recorded in ``renamed`` as a path.
    """
    if renamed is None:
        renamed = []
    if not isinstance(obj, dict) or message not in MESSAGES:
        return obj
    out = {}
    for key, value in obj.items():
        f = field(message, key)
        if f is None:
            out[key] = value
            continue
        if key != f.json:
            renamed.append("{}.{}".format(path, key) if path else key)
            if f.json in obj:
                # both spellings present: keep the JSON name's value
                continue
        sub = "{}.{}".format(path, f.json) if path else f.json
        if is_message(f.type):
            if f.repeated and isinstance(value, list):
                value = [camelise(v, f.type, "{}[{}]".format(sub, i), renamed) for i, v in enumerate(value)]
            elif isinstance(value, dict):
                value = camelise(value, f.type, sub, renamed)
        out[f.json] = value
    return out


def walk(obj, message: str, path: str = "") -> Iterator[Tuple[str, str, dict]]:
    """Yield ``(path, message, dict)`` for ``obj`` and every message inside it."""
    if not isinstance(obj, dict) or message not in MESSAGES:
        return
    yield path, message, obj
    for key, value in obj.items():
        f = field(message, key)
        if f is None or not is_message(f.type):
            continue
        sub = "{}.{}".format(path, key) if path else key
        if f.repeated and isinstance(value, list):
            for i, v in enumerate(value):
                yield from walk(v, f.type, "{}[{}]".format(sub, i))
        elif isinstance(value, dict):
            yield from walk(value, f.type, sub)


def ontology_classes(obj, message: str, path: str = "") -> Iterator[Tuple[str, dict]]:
    """Every OntologyClass inside ``obj``, with its path."""
    for p, m, d in walk(obj, message, path):
        if m == "OntologyClass":
            yield p, d
