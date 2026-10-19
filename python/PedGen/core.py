import os
import random
from collections import deque
import pandas as pd
import networkx as nx
#matplotlib is imported only to draw (plot_pedigree_tree), as it is slow to import and isn't needed to generate pedigrees

def no_parent(parent_id):
    '''
    Whether a parent ID means that the parent isn't in the pedigree: 0, however it was read (0, 0.0 or '0'), or a missing value
    '''
    if parent_id is None:
        return True
    try:
        if pd.isna(parent_id):
            return True
    except (TypeError, ValueError):
        pass
    text = str(parent_id).strip()
    if text == '':
        return True
    try:
        return float(text) == 0
    except ValueError:
        return False

def construct_pedigree_graph(df):
    G = nx.DiGraph()

    for _, row in df.iterrows():
        # Make sure IndividualID is treated as a string or int consistently if needed
        G.add_node(row['IndividualID'],
                  family=row['FamilyID'],
                  sex=row['Sex'],
                  phenotype=row['Phenotype'])

    for _, row in df.iterrows():
        paternal_id = row['PaternalID']
        maternal_id = row['MaternalID']
        individual_id = row['IndividualID']

        # a parent of 0 means unknown, whether it was read as a whole number, a decimal or text
        if not no_parent(paternal_id):
            G.add_edge(paternal_id, individual_id)
        if not no_parent(maternal_id):
            G.add_edge(maternal_id, individual_id)

    return G

def generations(G):
    '''
    Each person's generation in a pedigree graph, counting from 0 for the oldest.
    A child is one generation below its parents, so partners share a generation, and someone who married into the family
    is in their partner's generation, however many of their own ancestors are drawn. Where that can't hold throughout,
    as when people of different generations have children together, each child is put one generation below its lower
    parent, and each person with no parents in the pedigree one generation above their highest child.
    '''
    generation = {}
    order = list(nx.topological_sort(G))
    for component in nx.weakly_connected_components(G):
        people = [n for n in order if n in component]
        # spreading out from one person to the whole family, a child one generation below a parent and a parent one above a child
        level = {people[0]: 0}
        queue = deque([people[0]])
        consistent = True
        while queue:
            n = queue.popleft()
            for neighbour, step in [(c, 1) for c in G.successors(n)] + [(p, -1) for p in G.predecessors(n)]:
                if neighbour not in level:
                    level[neighbour] = level[n] + step
                    queue.append(neighbour)
                elif level[neighbour] != level[n] + step:
                    consistent = False
        if not consistent:
            level = {}
            for n in people:
                parents = list(G.predecessors(n))
                level[n] = max(level[p] for p in parents) + 1 if parents else 0
            for n in people:
                children = list(G.successors(n))
                if not list(G.predecessors(n)) and children:
                    level[n] = min(level[c] for c in children) - 1
        oldest = min(level.values())
        for n, l in level.items():
            generation[n] = l - oldest
    return generation

def generation_layout(G):
    '''
    Positions for drawing a pedigree graph without Graphviz: one row per generation (see generations()), the oldest at the top,
    so that partners are drawn side by side.
    '''
    generation = generations(G)
    rows = {}
    for n in G.nodes:
        rows.setdefault(generation[n], []).append(n)
    if not rows:
        return {}
    levels = sorted(rows)
    # order each row by the average position of the people it's joined to in the row above, then below,
    # a few times over, so that fewer lines cross (the barycentre method)
    place = {n: i for row in rows.values() for i, n in enumerate(row)}
    for _ in range(4):
        for sweep in (levels[1:], levels[-2::-1]):
            for level in sweep:
                def barycentre(n):
                    linked = [m for m in nx.all_neighbors(G, n) if generation[m] != level]
                    return sum(place[m] for m in linked) / len(linked) if linked else place[n]
                rows[level].sort(key=barycentre)
                for i, n in enumerate(rows[level]):
                    place[n] = i
    widest = max(len(row) for row in rows.values())
    pos = {}
    for level, row in rows.items():
        offset = (widest - len(row)) / 2
        for i, n in enumerate(row):
            pos[n] = (offset + i, -level)
    return pos

def plot_pedigree_tree(df, title="Pedigree (Tree Layout)"):
    import matplotlib.pyplot as plt

    G = construct_pedigree_graph(df)
    fig_size = (10, 5)
    f = plt.figure(figsize=fig_size)

    try:
        from networkx.drawing.nx_agraph import graphviz_layout
        pos = graphviz_layout(G, prog='dot')  # 'dot' gives top-down DAG style
    except ImportError:
        # PyGraphviz isn't installed (it needs Graphviz itself): draw one row per generation instead
        pos = generation_layout(G)

    #Separating nodes by sex
    males = [n for n in G.nodes if G.nodes[n].get('sex') == 1]
    females = [n for n in G.nodes if G.nodes[n].get('sex') == 2]
    unknown = [n for n in G.nodes if G.nodes[n].get('sex') not in (1, 2)]

    #Coloring nodes based on phenotype
    male_colors = ['red' if G.nodes[n].get('phenotype') == 2 else 'lightblue' for n in males]
    female_colors = ['red' if G.nodes[n].get('phenotype') == 2 else 'lightblue' for n in females]
    unknown_colors = ['red' if G.nodes[n].get('phenotype') == 2 else 'lightblue' for n in unknown]

    #Draw edges
    nx.draw_networkx_edges(G, pos, arrows=True)

    #Draw nodes
    nx.draw_networkx_nodes(G, pos, nodelist=males, node_shape='s', node_color=male_colors, label='Male')
    nx.draw_networkx_nodes(G, pos, nodelist=females, node_shape='o', node_color=female_colors, label='Female')
    if unknown:
        nx.draw_networkx_nodes(G, pos, nodelist=unknown, node_shape='d', node_color=unknown_colors, label='Unknown sex')
    
    #Add labels
    nx.draw_networkx_labels(G, pos)

    plt.title(title)
    plt.axis('off')
    plt.show()

    return f


# the most pedigrees made in looking for one with min_affected affected people
MAX_TRIES = 1000


def pedigree_generator(max_children, FamilyID, mode, generation_count, SpouseLikelihood=0.6, AffectedSpouse= True, BackpropLikelihood= 0.25, alt_freq= 0.001, seed= None, CousinLikelihood= 0.0, min_affected= 1):
        '''
        Generates a pedigree by Mendelian inheritance from an affected founder, with partners and their
        ancestors drawn from a population in Hardy-Weinberg equilibrium.

        PARAMETERS:
        -----------
        max_children (int): the most children a couple can have (at least 1)
        FamilyID (string): the family's id in the pedigree
        mode ('AD' or 'AR'): autosomal dominant or autosomal recessive
        generation_count (int): the number of generations
        SpouseLikelihood (float, 0-1): the chance that a child has a partner, and so children of their own (the first child always does, in every generation but the last)
        AffectedSpouse (bool): whether partners can carry the alternate allele
        BackpropLikelihood (float, 0-1): the chance that a partner's parents are added, and theirs, and so on
        alt_freq (float, 0-1): the frequency of the alternate allele in the population, 0.001 unless given: a rare
            allele, as a rare disease's is. It also sets how likely an affected founder is to have two copies of it
            in a dominant pedigree.
        seed (int, optional): makes the pedigree reproducible: the same seed and settings always give the same pedigree.
            Without a seed, Python's shared random number generator is used, as before.
        CousinLikelihood (float, 0-1): the chance that a descendant of the founder who has a partner marries a cousin
            (another descendant of the founder in the same generation, not a brother or sister, who has no partner
            yet), when there is one, rather than someone from outside the family. A rare recessive allele seldom
            comes together twice in a family in any other way. 0 unless given.
        min_affected (int): makes pedigrees until one has at least this many affected people, as families come to
            notice through their affected members (1 unless given). ValueError if none of MAX_TRIES has them.

        RETURN:
        -------
        DataFrame with one row per person: FamilyID, IndividualID, PaternalID, MaternalID, Sex (1 male, 2 female),
        Phenotype (1 unaffected, 2 affected) and Genotype (the number of alternate alleles)
        '''
        random = _random_source(seed)

        #-------------------------------------------
        # Helper Functions for Pedigree Propigation
        #-------------------------------------------

        '''
        Basic helper function to add new entry to pedigree dataframe
        '''
        def entry_generator(IndividualID, PaternalID, MaternalID, Sex, Phenotype, Genotype):
            nonlocal family_df
            family_df.loc[IndividualID] = [FamilyID, PaternalID, MaternalID, Sex, Phenotype, Genotype]

        '''
        Helper function to translate between genotype and phenotype
        Dependant on the mode of inheritance
        Input: genotype(int(0,1,2))
        Output: phenotype(int(1,2))
        '''
        def genotype_interpreter(genotype):
            if mode == 'AR':
                phenotype = 2 if genotype == 2 else 1
            if mode == 'AD':
                phenotype = 2 if genotype == 2 or genotype == 1 else 1
            return phenotype

        def calc_inheritance_weights(p,q):
            return inheritance_weights(p, q)

        '''
        Wrapper function that generates the primary founder of the pedigree
        By default, this individual is affected
        If AD, heterozygous or homozygous in the proportions in which affected people are in the population (2pq to
        q squared), so almost always heterozygous for a rare allele.
        If AR, 100% chance homozygous.
        Input:
        Output:
        '''
        def primary_founder_generator():
            nonlocal family_df

            if mode == 'AD':
                het, hom = 2*(1-alt_freq)*alt_freq, alt_freq**2
                Genotype = random.choices(population= [1,2],
                                          weights= (het, hom))[0] if het + hom > 0 else 1
            elif mode == 'AR':
                Genotype= 2

            entry_generator(IndividualID= 1,
                            PaternalID= 0,
                            MaternalID= 0,
                            Sex= random.randint(1,2),
                            Phenotype= 2,
                            Genotype= Genotype)
            generation_of[1] = 0
            descendants.add(1)
        '''
        Wrapper function that generates spouses unrelated to primary founder
        Spouse sex dependent on the relative of primary founder.
        Genotype and phenotype dependent on the mode of inheritance and affected spouse paramter.
        Input: relativeID(int)
        Ouput: n/a
        '''
        def spouse_generator(RelativeAnchorID):
            nonlocal family_df, alt_freq, ref_freq

            pp = ref_freq**2
            pq2 = 2*ref_freq*alt_freq
            qq = alt_freq**2

            Sex= 1 if family_df.loc[RelativeAnchorID]['Sex'] == 2 else 2

            if AffectedSpouse:
                Genotype= random.choices(population= [0,1,2],
                                          weights= (pp, pq2, qq),
                                          k=1)[0]

            else:
                Genotype = 0

            entry_generator(IndividualID= len(family_df)+1,
                            PaternalID= 0,
                            MaternalID= 0,
                            Sex= Sex,
                            Phenotype= genotype_interpreter(Genotype),
                            Genotype= Genotype)
        '''
        Wrapper function that generates an entry for the child of two given individuals.
        Child's genotype is chosen from list of allowed gentypes given parents genotypes with equal likelihood.
        Input: PaternalID(int), MaternalID(int)
        Output: n/a
        '''
        def child_generator(PaternalID, MaternalID):
            nonlocal family_df, inheritance_patterns

            parentalGenotype = (int(family_df.loc[PaternalID]['Genotype']), int(family_df.loc[MaternalID]['Genotype']))

            Genotype = random.choices(population= inheritance_patterns['forward_genotypes'][parentalGenotype],
                                      weights= inheritance_patterns['forward_weights'][parentalGenotype],
                                      k=1)[0]

            entry_generator(IndividualID= len(family_df)+1,
                            PaternalID= PaternalID,
                            MaternalID= MaternalID,
                            Sex= random.randint(1,2),
                            Phenotype= genotype_interpreter(Genotype),
                            Genotype= Genotype)
        #---------------------------------------
        # Primary Pedigree Contruction Functions
        #---------------------------------------
        '''
        Function that recursively constructs pedigree in backward direction.
        Infers ancestors of individuals unrelated to primary founder as they are added.
        Input: current_generation(int), RealativeAnchorID(int)
        Output: n/a
        '''
        def recursive_history_backprop(current_generation, RelativeAnchorID):
            nonlocal family_df, generation_count, inheritance_patterns, BackpropLikelihood

            BackpropRNG = random.randint(1,100)/100

            if current_generation > 0 and BackpropRNG <= BackpropLikelihood:

                GenotypeTup = random.choices(population= inheritance_patterns['reverse_genotypes'][family_df.loc[RelativeAnchorID]['Genotype']],
                                                    weights= inheritance_patterns['reverse_weights'][family_df.loc[RelativeAnchorID]['Genotype']],
                                                    k=1)[0]

                ID_list = ['PaternalID', 'MaternalID']

                for i in range(2):
                    entry_generator(IndividualID= len(family_df)+1,
                                    PaternalID= 0,
                                    MaternalID= 0,
                                    Sex= 1 + i,
                                    Phenotype= genotype_interpreter(GenotypeTup[i]),
                                    Genotype= GenotypeTup[i])
                    family_df.at[RelativeAnchorID, ID_list[i]] = len(family_df)
                    recursive_history_backprop(current_generation-1, len(family_df))

        '''
        A cousin for a descendant of the founder to marry: another descendant in the same generation, of the
        other sex, with no partner yet, who isn't a brother or sister. One is chosen at random; None if there are none.
        (The pedigree is built one branch at a time, so the cousins are in the branches built already.)
        Input: RelativeAnchorID(int), current_generation(int)
        Output: IndividualID(int) or None
        '''
        def cousin_of(RelativeAnchorID, current_generation):
            me = family_df.loc[RelativeAnchorID]
            free = [p for p in sorted(descendants)
                    if p != RelativeAnchorID and generation_of.get(p) == current_generation and p not in partnered
                    and family_df.loc[p]['Sex'] != me['Sex']
                    and (family_df.loc[p]['PaternalID'], family_df.loc[p]['MaternalID']) != (me['PaternalID'], me['MaternalID'])]
            return random.choice(free) if free else None

        '''
        Function that recursively constructs pedigree in forward direction.
        Input: current_generation(int), RelativeAnchorID(int)
        Output: n/a
        '''
        def recursive_pedigree_construction(current_generation, RelativeAnchorID):
            nonlocal family_df, max_children, generation_count

            if current_generation < generation_count-1:

                # a partner: now and then a cousin, if one is free, and otherwise someone from outside the family
                cousin = None
                if CousinLikelihood and current_generation > 0 and random.random() < CousinLikelihood:
                    cousin = cousin_of(RelativeAnchorID, current_generation)
                if cousin is None:
                    spouse_generator(RelativeAnchorID= RelativeAnchorID)
                    partner = len(family_df)
                else:
                    partner = cousin
                partnered.update((RelativeAnchorID, partner))

                #Determining Parental Sex for next generation
                if family_df.loc[RelativeAnchorID]['Sex'] == 1:
                    PaternalID = RelativeAnchorID
                    MaternalID = partner
                else:
                    PaternalID = partner
                    MaternalID = RelativeAnchorID

                # (a cousin's parents are in the pedigree already)
                if BackpropLikelihood and cousin is None:
                    recursive_history_backprop(current_generation, partner)

                for child in range(random.randint(1, max_children)):
                    child_generator(PaternalID= PaternalID, MaternalID= MaternalID)
                    generation_of[len(family_df)] = current_generation + 1
                    descendants.add(len(family_df))
                    reproductive_rng = random.randint(1,100)/100
                    #checks if a spouse should be generated for the newly generated child
                    #spouse must be generated for at least one child (the first) to ensure generation count
                    if reproductive_rng <= SpouseLikelihood or child == 0:
                        recursive_pedigree_construction(current_generation+1, len(family_df))


        #--------------------------------------------
        # Construct Inheritence Pattern Dictionary
        #--------------------------------------------
        ref_freq = 1 - alt_freq
        inheritance_patterns = calc_inheritance_weights(ref_freq, alt_freq)
        if int(min_affected) < 1:
            raise ValueError(f'min_affected must be 1 or more, not {min_affected}')

        # pedigrees are made until one has min_affected affected people (the founder is one)
        for attempt in range(MAX_TRIES):
            #-------------------------------------
            # 1. Construct the empty data frame
            #-------------------------------------
            pedigree_construction_columns = ['FamilyID', 'IndividualID', 'PaternalID', 'MaternalID', 'Sex', 'Phenotype', 'Genotype']
            family_df = pd.DataFrame(columns= pedigree_construction_columns)
            family_df.set_index('IndividualID', inplace=True)
            # each person's generation (the founder's is 0), the founder and their descendants, and who has a partner
            generation_of, descendants, partnered = {}, set(), set()

            #-------------------------------------
            # 2. Generating Primary Founder
            #-------------------------------------
            primary_founder_generator()

            #----------------------------------------
            # 3. Generating Pedigree
            #----------------------------------------
            recursive_pedigree_construction(current_generation= 0, RelativeAnchorID= 1)

            #-------------------------------
            # 4. Resetign Standard Indexing
            # #-------------------------------
            family_df.reset_index(inplace= True)

            if int((family_df['Phenotype'] == 2).sum()) >= min_affected:
                return family_df

        raise ValueError(f'none of {MAX_TRIES:,} pedigrees had {min_affected} affected people: give a higher allele '
                         f'frequency, more generations or children, or (for a recessive condition) a chance that '
                         f'cousins marry')

def gen_PED_export(ped_df, output_dir='.'):
    '''
    Writes the pedigree as a PED file named after its family, 'FamilyID'.ped, in output_dir, and returns the file's path.
    '''
    family_id = ped_df['FamilyID'].iloc[0]
    os.makedirs(output_dir, exist_ok= True)
    path = os.path.join(output_dir, f'{family_id}.ped')
    ped_df.to_csv(path,
                  columns= ['FamilyID', 'IndividualID', 'PaternalID', 'MaternalID', 'Sex', 'Phenotype'],
                  header= False,
                  index= False,
                  sep= '\t',
                  )
    return path


def gen_genotype_export(ped_df, path, alt_freq=None, variant='causal'):
    '''
    Writes the number of copies of the alternate allele that each person in a generated pedigree has (its Genotype
    column) as a table that PedNet reads as a candidate variant (pednet rank FAMILY.ped FILE), and returns the path.

    The table has a row for the variant: its name (variant), its chromosome (an autosome, as the modes generated are
    autosomal), the alternate allele's frequency in the population if alt_freq is given (as given to
    pedigree_generator), and a column for each person, named by their IndividualID.
    '''
    folder = os.path.dirname(str(path))
    if folder:
        os.makedirs(folder, exist_ok= True)
    people = [str(i) for i in ped_df['IndividualID']]
    copies = [str(int(g)) for g in ped_df['Genotype']]
    header = ['variant', 'chrom'] + (['af'] if alt_freq is not None else []) + people
    row = [variant, 'autosome'] + ([repr(float(alt_freq))] if alt_freq is not None else []) + copies
    with open(path, 'w', encoding= 'utf-8') as handle:
        handle.write('\t'.join(header) + '\n' + '\t'.join(row) + '\n')
    return path


def _random_source(seed):
    '''Python's shared random number generator, or a separate one started from seed.'''
    return random if seed is None else random.Random(seed)


def inheritance_weights(p, q):
    '''
    Genotype probabilities for passing the alternate allele down a family (forward), and for choosing the
    parents of someone who married in (reverse). A genotype counts alternate alleles: 0 homozygous reference,
    1 heterozygous, 2 homozygous alternate. p and q are the reference and alternate allele frequencies.

    Forward, a child's genotype follows Mendel's laws: each parent passes on one of their two alleles at random.
    Reverse, the parents' genotypes are chosen given their child's by Bayes' theorem. Each pair of parental
    genotypes is weighted by its Hardy-Weinberg frequency times the chance that it gives the child's genotype,
    so ancestors chosen this way are in Hardy-Weinberg proportions, as people in the population are.
    '''
    hardy_weinberg = {0: p**2, 1: 2*p*q, 2: q**2}
    passes_alt = {0: 0.0, 1: 0.5, 2: 1.0}  # chance that a parent with this genotype passes on the alternate allele

    forward_genotypes, forward_weights = {}, {}
    reverse_genotypes = {2: [], 1: [], 0: []}
    reverse_weights = {2: [], 1: [], 0: []}
    for paternal in (2, 1, 0):
        for maternal in (2, 1, 0):
            a, b = passes_alt[paternal], passes_alt[maternal]
            child = {2: a*b, 1: a*(1-b) + (1-a)*b, 0: (1-a)*(1-b)}
            possible = [g for g in (2, 1, 0) if child[g] > 0]
            #(paternal genotype, maternal genotype) -> [possible child genotypes]
            forward_genotypes[(paternal, maternal)] = possible
            forward_weights[(paternal, maternal)] = [child[g] for g in possible]
            #child genotype -> [possible (paternal, maternal) genotypes]
            for g in possible:
                reverse_genotypes[g].append((paternal, maternal))
                reverse_weights[g].append(hardy_weinberg[paternal] * hardy_weinberg[maternal] * child[g])

    return {
        'forward_genotypes': forward_genotypes,
        'forward_weights': forward_weights,
        'reverse_genotypes': reverse_genotypes,
        'reverse_weights': reverse_weights,
    }