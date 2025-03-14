# -*- coding: utf-8 -*-
"""QUADRO HORÁRIOS VER.2.1 DE 28.02.25.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1kBPR9rX79PAGV4eKLHMAJ82skr4l6-GP
"""

import pandas as pd
import random
from collections import defaultdict, namedtuple, OrderedDict

# =========================================================================
# PARÂMETROS GERAIS
# =========================================================================
dias_semana = ["SEG","TER","QUA","QUI","SEX"]
tempos = [1,2,3,4,5]
NUM_ITERACOES = 10000  # quantas vezes tentamos alocar do zero para achar melhor solucao

# =========================================================================
# 1) LEITURA DOS ARQUIVOS
# =========================================================================
df_prof = pd.read_excel("professores.xlsx")
df_demanda_raw = pd.read_excel("demanda.xlsx")

# =========================================================================
# 2) CRIAR DICIONÁRIO DE DISPONIBILIDADE
#    disponib[prof][turno][dia][tempo] = True/False
# =========================================================================
disponib = {}
for i, row in df_prof.iterrows():
    servidor = row["SERVIDOR"]
    turno    = row["TURNO"]

    if servidor not in disponib:
        disponib[servidor] = {}
    if turno not in disponib[servidor]:
        disponib[servidor][turno] = {}

    for d in dias_semana:
        if d not in disponib[servidor][turno]:
            disponib[servidor][turno][d] = {}
        for t in tempos:
            col = f"{d}{t}"  # ex.: SEG1, SEG2 ...
            if col in row:
                val = row[col]
                disponib[servidor][turno][d][t] = (val == 1)
            else:
                disponib[servidor][turno][d][t] = False

# =========================================================================
# 3) FILTRAR "APOIO" E MONTAR DEMANDA
#    Regra #4: "APOIO não é disciplina => não alocar"
# =========================================================================
df_demand = df_demanda_raw[ df_demanda_raw["DISC"] != "APOIO" ].copy()

# Montar em uma lista de dict
Pedido = namedtuple("Pedido","prof turno nivel serie turma disc ch")
demanda = []
for i, row in df_demand.iterrows():
    demanda.append(Pedido(
        prof  = row["SERVIDOR"],
        turno = row["TURNO"],
        nivel = row["NIVEL"],
        serie = str(row["SERIE/ANO"]),
        turma = str(row["TURMA"]),
        disc  = row["DISC"],
        ch    = int(row["CH.TURMA"])
    ))

# =========================================================================
# 4) ESTRUTURA DE ALOCACAO
#    horario[turno][nivel][dia][(serie, turma)] = { tempo: (prof, disc) }
# =========================================================================

def cria_horario_vazio(demanda):
    """Gera a estrutura vazia para todos (turno,nivel,dia,serie,turma) que aparecem na demanda."""
    horario = {}
    # Descobrir todos turnos/niveis
    combos = set()
    for ped in demanda:
        combos.add((ped.turno, ped.nivel))
    # Criar
    for (tnr, niv) in combos:
        if tnr not in horario:
            horario[tnr] = {}
        if niv not in horario[tnr]:
            horario[tnr][niv] = {}
        for d in dias_semana:
            horario[tnr][niv][d] = {}
    # Para cada item da demanda, garantir a chave (serie,turma)
    for ped in demanda:
        for d in dias_semana:
            if (ped.serie, ped.turma) not in horario[ped.turno][ped.nivel][d]:
                horario[ped.turno][ped.nivel][d][(ped.serie, ped.turma)] = {}
    return horario

# =========================================================================
# 5) FUNÇÕES DE VERIFICAÇÃO DE REGRAS
# =========================================================================

def professor_disponivel(prof, turno, dia, tempo):
    """Verifica se professor existe e se está True nesse dia/tempo."""
    if prof not in disponib:
        return False
    if turno not in disponib[prof]:
        return False
    return disponib[prof][turno][dia][tempo]

def professor_ja_ocupado_esse_tempo(horario, prof, turno, nivel, dia, tempo):
    """Se o professor já está em outra turma nesse dia/tempo."""
    for (serie_t, aloc_dic) in horario[turno][nivel][dia].items():
        if tempo in aloc_dic:
            (p, d) = aloc_dic[tempo]
            if p == prof:
                return True
    return False

def turma_ja_tem_aula(horario, turno, nivel, dia, serie, turma, tempo):
    """Se a turma já tem algo nesse tempo."""
    return (tempo in horario[turno][nivel][dia][(serie,turma)])

def check_buraco(horario, turno, nivel, dia, serie, turma):
    """
    Garante que se a turma ocupar X tempos, deve ser 1..X (sem pular) e começar no 1.
    """
    aloc = horario[turno][nivel][dia][(serie,turma)]
    if not aloc:
        return False
    tempos_ocup = sorted(aloc.keys())
    # Se o 1o tempo nao for 1, buraco:
    if tempos_ocup[0] != 1:
        return True
    # Se há pulos até o max
    maxi = max(tempos_ocup)
    for t in range(1, maxi+1):
        if t not in aloc:
            return True
    return False

def professor_ja_na_mesma_turma_esse_dia(horario, prof, turno, nivel, dia, serie, turma):
    """
    Nova regra: "evitar ao máximo que um mesmo professor esteja na mesma turma no mesmo dia mais de uma vez"
    (Independente da disciplina.)
    """
    aloc = horario[turno][nivel][dia][(serie,turma)]
    for (tempo, (p, dsc)) in aloc.items():
        if p == prof:
            return True
    return False

def professor_tem_gap(horario, prof, turno, nivel, dia):
    """
    Verifica se o professor ficou com "furo" entre tempos de aula nesse dia.
    Exemplo: Ele dá aula no tempo 1 e 3, mas não no 2 => gap.
    REGRAS: "evitar ao máximo"
    => iremos punir com uma heurística, mas não necessariamente proibir.
    """
    # Descobrir em quais tempos o professor dá aula nesse dia:
    tempos_prof = []
    for (st, aloc_dic) in horario[turno][nivel][dia].items():
        for tm, (p, dsc) in aloc_dic.items():
            if p == prof:
                tempos_prof.append(tm)
    if len(tempos_prof) <= 1:
        return False
    tempos_prof.sort()
    # se há "furo" interno
    for i in range(len(tempos_prof)-1):
        if tempos_prof[i+1] - tempos_prof[i] > 1:
            return True
    return False

def aloca_tempo(horario, ped, dia, tempo):
    """Faz a alocação propriamente dita."""
    horario[ped.turno][ped.nivel][dia][(ped.serie,ped.turma)][tempo] = (ped.prof, ped.disc)

def desaloca_tempo(horario, ped, dia, tempo):
    """Desaloca se existir."""
    turmadic = horario[ped.turno][ped.nivel][dia][(ped.serie,ped.turma)]
    if tempo in turmadic:
        del turmadic[tempo]

def pode_alocar(horario, ped, dia, tempo, permitir_repeticao=False):
    """
    Checa se podemos alocar esse (prof,disc) na (turma) sem violar as regras estritas:
      1. professor disponível
      2. professor não em outro local no mesmo tempo
      3. não criar buraco para a turma
      4. evitar ao máximo repetição do mesmo professor na mesma turma no mesmo dia (regra nova):
         - Por default, não permitir. Mas se 'permitir_repeticao=True', a heurística vai usar
           se não couber de outro jeito.
    """
    # Regras estritas:
    # (1) e (2):
    if not professor_disponivel(ped.prof, ped.turno, dia, tempo):
        return False
    if professor_ja_ocupado_esse_tempo(horario, ped.prof, ped.turno, ped.nivel, dia, tempo):
        return False
    # (3) se alocar e vira buraco?
    aloca_tempo(horario, ped, dia, tempo)
    if check_buraco(horario, ped.turno, ped.nivel, dia, ped.serie, ped.turma):
        desaloca_tempo(horario, ped, dia, tempo)
        return False
    # (4) repetição do mesmo prof nessa turma/dia?
    # Se professor_ja_na_mesma_turma_esse_dia => recusar a menos que permitir_repeticao=True
    # Precisamos ver se já existia antes de alocar este tempo. Então, vamos "desalocar", checar e realocar se ok:
    # mas alocamos de novo para ver se gerou buraco acima. Então iremos checar no "pre aloc".
    # Solução simples: checar antes de alocar:
    desaloca_tempo(horario, ped, dia, tempo)
    ja_tinha = professor_ja_na_mesma_turma_esse_dia(horario, ped.prof, ped.turno, ped.nivel, dia, ped.serie, ped.turma)
    if ja_tinha and not permitir_repeticao:
        return False
    # Se chegou até aqui, realocamos e passamos
    aloca_tempo(horario, ped, dia, tempo)
    return True

def conta_gaps_prof(horario, ped, dia):
    """Conta quantos "gaps" esse professor tem no dia. (Heurística: penalização.)"""
    has_gap = professor_tem_gap(horario, ped.prof, ped.turno, ped.nivel, dia)
    return 1 if has_gap else 0

# =========================================================================
# 6) HEURÍSTICA DE ALOCAÇÃO COM TENTATIVAS MÚLTIPLAS
# =========================================================================

def alocar_demanda(horario, demanda):
    """
    Aloca a demanda no 'horario' e retorna a lista de (pedido, ch_nao_alocado).
    Fazemos loops pelos dias e tempos, ou outra heurística.
    Tenta evitar repetições do mesmo professor na mesma turma (mas se não couber, permite).
    Tenta também evitar "gap" para o professor.
    """
    # Faremos uma simples varredura da "demanda" em ordem aleatória,
    # e para cada item, tentamos alocar "ch" tempos.
    # No interior, tentamos varrer dias e tempos também em ordem aleatória (para espalhar).

    dem_local = list(demanda)
    random.shuffle(dem_local)  # aleatorizar a ordem de pedidos

    dias_seq = list(dias_semana)
    tempos_seq = list(tempos)

    nao_alocados = []

    for ped in dem_local:
        ch_rest = ped.ch
        # Tentar alocar ch_rest
        # varrer dias e tempos de forma random
        ds = dias_seq[:]
        random.shuffle(ds)
        for d in ds:
            ts = tempos_seq[:]
            random.shuffle(ts)
            for t in ts:
                if ch_rest <= 0:
                    break
                # Primeira tentativa: nao permitir repeticao (preferir 1x/dia)
                if pode_alocar(horario, ped, d, t, permitir_repeticao=False):
                    # Checamos se gerou gap grande para o professor:
                    # Se gerou gap, vamos desalocar e tentar com repeticao ou outro tempo
                    if conta_gaps_prof(horario, ped, d) > 0:
                        # desalocar e ver se "permitir_repeticao" ajuda
                        desaloca_tempo(horario, ped, d, t)
                        # Tentar permitir repeticao do professor nessa turma:
                        if pode_alocar(horario, ped, d, t, permitir_repeticao=True):
                            # ok, alocou com repeticao
                            ch_rest -= 1
                    else:
                        # ok, sem gap
                        ch_rest -= 1
            if ch_rest <= 0:
                break

        # Se ainda sobra, repetimos, mas agora sempre permitir_repeticao
        if ch_rest > 0:
            for d in ds:
                ts = tempos_seq[:]
                random.shuffle(ts)
                for t in ts:
                    if ch_rest <= 0:
                        break
                    if pode_alocar(horario, ped, d, t, permitir_repeticao=True):
                        # Checar gap
                        if conta_gaps_prof(horario, ped, d) > 0:
                            # Aceitamos pois nao tem outro geito
                            pass
                        ch_rest -= 1
                if ch_rest <= 0:
                    break

        if ch_rest > 0:
            # sobrou
            nao_alocados.append((ped, ch_rest))

    return nao_alocados

def constroi_solucao(demanda):
    """Constrói um horario vazio e aloca."""
    horario_temp = cria_horario_vazio(demanda)
    nao_aloc = alocar_demanda(horario_temp, demanda)
    return (horario_temp, nao_aloc)

# Repetimos a construção várias vezes e pegamos a que tenha menos nao_alocados
melhor_horario = None
melhor_nao_alocados = None
menor_sobra = float("inf")

for i in range(NUM_ITERACOES):
    horario_cand, nao_aloc_cand = constroi_solucao(demanda)
    sobra = sum(x[1] for x in nao_aloc_cand)
    if sobra < menor_sobra:
        menor_sobra = sobra
        melhor_horario = horario_cand
        melhor_nao_alocados = nao_aloc_cand

print(f"Melhor solução encontrada após {NUM_ITERACOES} iterações: {menor_sobra} tempos não alocados.")

# =========================================================================
# 7) LISTAR OS NÃO ALOCADOS
# =========================================================================
if menor_sobra > 0:
    print(f"[Aviso] Não foi possível alocar {menor_sobra} tempos.")
    print("LISTA DE NAO ALOCADOS (prof,disc,turno,nivel,serie,turma, quantidade):")
    for (ped, c) in melhor_nao_alocados:
        if c > 0:
            print(f" - {ped.prof}, {ped.disc}, {ped.turno}, {ped.nivel}, {ped.serie}-{ped.turma}, sobrou {c}")

    # Se quiser salvar em XLSX:
    df_na = []
    for (ped, c) in melhor_nao_alocados:
        if c>0:
            df_na.append({
                "SERVIDOR": ped.prof,
                "DISCIPLINA": ped.disc,
                "TURNO": ped.turno,
                "NIVEL": ped.nivel,
                "SERIE/ANO": ped.serie,
                "TURMA": ped.turma,
                "QUANTIDADE_NAO_ALOCADA": c
            })
    df_na_x = pd.DataFrame(df_na)
    df_na_x.to_excel("NAO_ALOCADOS.xlsx", index=False)
else:
    print("Todas as aulas foram alocadas com sucesso (0 não alocados).")

# =========================================================================
# 8) GERAR A PLANILHA FINAL POR TURMA (como antes)
#    e TAMBÉM UMA PLANILHA POR PROFESSOR
# =========================================================================

def gera_df_por_turma(horario):
    """
    Mesmo formato do script anterior:
    uma aba por (turno,nivel),
    colunas => 'SÉRIE-TURMA',
    linhas => (DIA,TEMPO),
    célula => "SERVIDOR+DISC".
    """
    from collections import defaultdict
    colunas_por_tn = defaultdict(set)

    # Descobrir as colunas
    for tnr in horario:
        for niv in horario[tnr]:
            for d in dias_semana:
                for (sa, tu), dicT in horario[tnr][niv][d].items():
                    colunas_por_tn[(tnr,niv)].add(f"{sa}-{tu}")

    # Montar dataframes
    dfs_por_aba = {}
    for tnr in horario:
        for niv in horario[tnr]:
            turmas_cols = sorted(list(colunas_por_tn[(tnr,niv)]))
            linhas = []
            for d in dias_semana:
                for tm in tempos:
                    row_dict = {
                        "TURNO": tnr,
                        "NIVEL": niv,
                        "DIA": d,
                        "TEMPO": tm
                    }
                    for col_turma in turmas_cols:
                        row_dict[col_turma] = ""
                    # Preenche
                    for (sa, tu), dicT in horario[tnr][niv][d].items():
                        col_name = f"{sa}-{tu}"
                        if tm in dicT:
                            (p, di) = dicT[tm]
                            row_dict[col_name] = f"{p}+{di}"
                    linhas.append(row_dict)
            df_aba = pd.DataFrame(linhas)
            dfs_por_aba[f"{tnr}_{niv}"] = df_aba
    return dfs_por_aba


def gera_df_por_professor(horario):
    """
    Precisamos agora de 1 aba para cada professor,
    com linhas => (DIA, TEMPO),
    colunas => TURMA/Disc? Ou "SÉRIE-TURMA"?
    O enunciado diz: "ao invés de turma na coluna, será o nome do professor e
    em cada linha a disciplina que ele ministra"?
    Mas precisamos algo coerente.
    Aqui faremos: 1 aba = 1 professor,
    colunas => "SÉRIE-TURMA" (ou "Turma-Disc"?),
    célula => "NIVEL" (ou "Disc"?).
    Vou supor colunas => "SERIE-TURMA-DISC" e a célula fica "DIA/TEMPO"?
    Ou invertido?
    O enunciado não é 100% claro.
    Faremos algo análogo: nas linhas, (DIA, TEMPO), colunas => "SERIE-TURMA (DISC)".
    """
    # Descobrir todos os professores
    profs_set = set()
    # Precisamos mapear, para cada professor, quais "SERIE-TURMA-DISC" ele atende
    # varrendo o horario
    mapping = defaultdict(set)  # mapping[prof] = set("serie-turma (disc)")

    # Precisamos também de uma forma de saber em qual dia/tempo esse prof dá aula
    # e para qual SERIE-TURMA-DISC
    # professor_hor[prof][ (dia,tempo) ] = list de (serie-turma-disc)
    professor_hor = defaultdict(lambda: defaultdict(list))

    for tnr in horario:
        for niv in horario[tnr]:
            for d in dias_semana:
                for (sa, tu), dicT in horario[tnr][niv][d].items():
                    for tm, (p, di) in dicT.items():
                        profs_set.add(p)
                        colname = f"{sa}-{tu}({di})"
                        mapping[p].add(colname)
                        professor_hor[p][(d,tm)].append( (tnr, niv, sa, tu, di) )

    # Para cada professor, criaremos um DF
    dfs_prof = {}
    for p in profs_set:
        cols_order = sorted(list(mapping[p]))
        # Montar as linhas => (DIA, TEMPO) sempre 5x5
        data_rows = []
        for d in dias_semana:
            for tm in tempos:
                row_dict = {
                    "PROFESSOR": p,
                    "DIA": d,
                    "TEMPO": tm
                }
                # inicializa
                for c in cols_order:
                    row_dict[c] = ""
                # preenche se houver alguma aula
                if (d,tm) in professor_hor[p]:
                    for (tnr, niv, sa, tu, di) in professor_hor[p][(d,tm)]:
                        cname = f"{sa}-{tu}({di})"
                        row_dict[cname] = f"{tnr}-{niv}"  # ou so "Ok" etc.
                data_rows.append(row_dict)
        df_p = pd.DataFrame(data_rows)
        dfs_prof[p] = df_p

    return dfs_prof


# Gera as planilhas com a melhor_horario
dfs_turma = gera_df_por_turma(melhor_horario)
dfs_prof  = gera_df_por_professor(melhor_horario)

# Salvar no Excel
with pd.ExcelWriter("QUADRO_HORARIOS_TURMAS.xlsx") as writer:
    for aba, df_ in dfs_turma.items():
        df_.to_excel(writer, sheet_name=aba, index=False)

with pd.ExcelWriter("QUADRO_HORARIOS_PROFESSORES.xlsx") as writer:
    for prof, df_ in dfs_prof.items():
        # Limitar nome da aba a 31 chars (limite do Excel):
        sheetname = prof[:31]
        df_.to_excel(writer, sheet_name=sheetname, index=False)

print("Arquivos gerados:")
print(" - QUADRO_HORARIOS_TURMAS.xlsx (uma aba por Turno_Nivel)")
print(" - QUADRO_HORARIOS_PROFESSORES.xlsx (uma aba por professor)")
if menor_sobra > 0:
    print(" - NAO_ALOCADOS.xlsx (lista dos não alocados)")