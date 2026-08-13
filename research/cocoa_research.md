# Cacao (Cocoa CFD) — Ricerca fondamentale e quantitativa

**Data:** 14 luglio 2026 · **Dati:** ICE Cocoa futures continuo (CC=F), 2000-01-03 → 2026-07-14, 6.652 barre giornaliere · **Analisi:** calcoli originali su dati reali (script `cocoa_quant.py`), COT CFTC live, conoscenza di dominio.

> ⚠️ **AGGIORNATO 13 agosto 2026.** Le sezioni 1-12 restano valide (analisi strutturale). Sono stati aggiunti: **§0** (cosa è successo negli ultimi mesi), **§13** (setup algoritmico + backtest) e una **correzione** al §8/§12 sul COT — il dato smentisce quanto avevo scritto a luglio.

**Stato al 13/08/2026:** $5.754/t · drawdown **−54%** dal massimo ($12.565, dic 2024) ma **+106% dal minimo** di $2.798 (fine feb 2026) · volatilità 21g **66% annua** (96° percentile storico) · speculatori **net short −13.320** (40% long), 17° percentile a 3 anni.

---

## 0. Cosa è successo negli ultimi mesi (lug 2025 → ago 2026)

Due movimenti opposti e violenti, entrambi con cause fondamentali identificabili.

### Fase A — Il crollo: da $8.500 a $2.798 (lug 2025 → 27 feb 2026, −67%)

| Mese | Var. | |
|---|---|---|
| lug-nov 2025 | −9,1% · −10,2% · −11,6% · −8,9% · −12,1% | discesa ordinata, cinque mesi consecutivi |
| dic 2025 | **+12,2%** | rimbalzo tecnico (falso segnale di fondo) |
| **gen 2026** | **−31,3%** | capitolazione |
| **feb 2026** | **−32,8%** | minimo a $2.798 |

**Le cause, in ordine di peso:**

1. **Surplus conclamato.** StoneX ha stimato un surplus mondiale di **287.000 t** per la stagione 2025/26 e altre 267.000 t per il 2026/27. A gennaio l'ICCO ha certificato scorte globali a **1,1 milioni di tonnellate**, +4,2% su base annua. Il deficit che aveva creato la bolla si era rovesciato.
2. **Distruzione della domanda.** I *grindings* (la macinazione, cioè il consumo reale) sono crollati: −6,7% nei primi tre trimestri 2025 tra Europa, Nordamerica e Asia, con l'Asia a −16% nel Q2. Il Q1 2026 europeo ha segnato **−7,8% a 325.895 t, il primo trimestre più debole in 17 anni**. A $10.000/t i cioccolatieri hanno riformulato le ricette e ridotto le percentuali di cacao — esattamente la "demand destruction" prevista.
3. **Sciopero degli acquirenti.** Con i prezzi in caduta, i compratori hanno smesso di comprare in attesa di prezzi migliori: fave ferme nei magazzini, in alcuni casi in deterioramento. È il classico circolo vizioso che accelera i crolli.
4. **Capitolazione politica.** La Costa d'Avorio ha **tagliato il prezzo al coltivatore di oltre il 60%**, a 1.200 franchi CFA/kg — la conferma ufficiale che il ciclo era girato.

### Fase B — La risalita: da $2.798 a $5.754 (mar → ago 2026, **+106%**)

| Mese | Var. |
|---|---|
| mar · apr · mag 2026 | +17,9% · +5,9% · +12,3% |
| **giu 2026** | **+27,5%** |
| lug · ago 2026 | +7,9% · +6,6% |

**Le cause:**

1. **Il raccolto 2026/27 si annuncia disastroso.** Il regolatore ghanese ha proiettato la produzione 2026/27 a **450.000-550.000 t contro le 750.000 t** attese per il 2025/26 — una caduta fino al 40%, per la combinazione di *swollen shoot*, alberi vecchi ed El Niño. In Costa d'Avorio le stime precoci indicano **1,8 milioni di t, −18%** rispetto ai 2,2 milioni del 2025/26, con sviluppo dei baccelli scarso.
2. **Meteo avverso.** Piogge eccessive hanno allagato le piantagioni in entrambi i Paesi, e i rilevamenti precoci mostrano formazione di *cherelle* (i baccelli giovani) sotto la media per il raccolto principale che parte a ottobre.
3. **El Niño di nuovo in formazione**, con il consueto anticipo di 6-12 mesi sull'offerta dell'Africa Occidentale.
4. **Accordo Ghana-Costa d'Avorio del 16 giugno 2026**: i due Paesi (oltre il 60% dell'offerta mondiale) hanno firmato una dichiarazione congiunta per allineare i prezzi al coltivatore e armonizzare i calendari di raccolta dal 2026/27. Il mercato l'ha letta come potere di prezzo concentrato — e infatti giugno è il mese del +27,5%.
5. **Ricoperture degli short.** Gli speculatori erano massicciamente corti (net −29.350 a giugno): la risalita li ha costretti a ricomprare, amplificando il movimento. Il net è passato da −29.350 a −13.320 in nove settimane.

**La lettura d'insieme:** è il superciclo descritto nel §3 che si ripete puntuale. Surplus → crollo → prezzi bassi che scoraggiano la cura degli alberi → nuovo deficit. Solo che stavolta il giro è stato **rapidissimo** (18 mesi invece di 3-5 anni) perché la malattia (swollen shoot) e l'età degli alberi hanno fatto da acceleratore strutturale.

**Il dato che pochi guardano:** questa risalita del +106% è avvenuta **con gli speculatori ancora net SHORT** (17° percentile a 3 anni). Non è un rally guidato dai fondi: è offerta reale che manca, con i fondi rimasti indietro. Chi conosce la storia del §3 sa che i grandi rally del cacao partono così.

---

## 1. Come funziona il mercato del cacao

**Formazione del prezzo.** Il prezzo mondiale nasce sui futures ICE, non sul fisico: i due contratti benchmark sono **ICE US "Cocoa" (simbolo CC, in $/tonnellata, consegna a New York)** e **ICE Europe "London Cocoa" (C, in £/t)**. Il fisico (fave alla frontiera di Abidjan o Tema) prezza a *differenziale* rispetto al future. La catena: coltivatore → acquirente locale/cooperativa → esportatore → trade house (Olam, Barry Callebaut, Cargill, Sucden, Touton) → grinder/cioccolatiere; ogni anello si copre sui futures, ed è questo hedging commerciale a dare liquidità al contratto.

**Spot vs futures vs CFD.** Lo *spot* è il fisico a pronti (inaccessibile al retail: lotti da container, qualità, logistica). Il *future* ICE è standardizzato: 10 tonnellate per contratto, scadenze mar/mag/lug/set/dic, consegna fisica possibile. Il **CFD di IC Markets ("Cocoa — Cocoa Futures")** replica il prezzo del future front-month: prezzo derivato dal contratto ICE più liquido, **niente consegna, niente scadenza gestita da te** — il broker effettua il *rollover* alla scadenza (con aggiustamento del prezzo pari al basis tra i due contratti, accreditato/addebitato). Nota dal PDF IC Markets: i futures CFD **non pagano swap** (costi nello spread), ma il rollover di scadenza c'è.

**Implicazione per il trader CFD:** stai tradando la curva futures, quindi anche il *contango/backwardation* conta: in backwardation ripida (tipica dei deficit) il rollover ti "regala" carry se sei long il front; in contango lo paghi.

---

## 2. Perché il cacao è così volatile

Volatilità strutturale misurata: **35% annua media 2000-2026** (2-3× un indice azionario), oggi 76%. Le ragioni, fattore per fattore:

| Fattore | Meccanismo | Importanza | Ritardo effetto | Esempio storico |
|---|---|---|---|---|
| **Concentrazione geografica dell'offerta** | Costa d'Avorio (~40-45%) + Ghana (~12-15%) = **oltre metà dell'offerta mondiale** in due Paesi confinanti con lo stesso clima. Nessuna commodity ha una concentrazione simile → ogni shock locale è uno shock globale | **ALTA (il fattore #1)** | Immediato sul sentiment, 3-9 mesi sui volumi | Il deficit 2023/24 di CIV+Ghana ha prodotto il +212% in 120 giorni (misurato) |
| **Clima / El Niño-La Niña** | El Niño → siccità e Harmattan intenso in Africa Occidentale → fioritura compromessa → raccolto -10/20%. La Niña → piogge eccessive → marciume e trasporti bloccati | **ALTA** | 6-12 mesi (dal segnale ENSO al raccolto) | El Niño 2015-16 (rally poi crollo 2017 su ripresa); El Niño 2023 → catalizzatore della bolla 2024 |
| **Malattie delle piante** | *Black pod* (fungo, esplode con umidità) e *Swollen Shoot Virus* (CSSV: pianta da estirpare, perdita permanente) riducono resa; il CSSV ha infettato quote enormi di alberi ivoriani | **ALTA (strutturale)** | Black pod: mesi; CSSV: anni (permanente) | 2023: black pod + CSSV insieme → collasso raccolto principale |
| **Invecchiamento alberi / sottoinvestimento** | Alberi >25 anni rendono meno; il farmgate price tenuto basso dai regolatori ha impedito reinvestimento per decenni → offerta rigida, incapace di rispondere ai prezzi per 3-4 anni (tempo di un albero nuovo) | **ALTA (spiega i supercicli)** | 3-5 anni | La bolla 2024 è figlia di 10 anni di sottoinvestimento |
| **Politiche governative (CCC/COCOBOD)** | Costa d'Avorio e Ghana fissano il prezzo al coltivatore e vendono forward l'export; il LID ($400/t "living income differential" dal 2019) altera i differenziali; annunci di farmgate price muovono le aspettative di offerta futura | **MEDIA-ALTA** | Settimane-mesi | Ghana 2024: COCOBOD incapace di consegnare i forward → rolled contracts → benzina sulla bolla |
| **Scorte mondiali / stock ICE** | Le scorte certificate ICE nei warehouse sono il buffer visibile: stock ai minimi = ogni notizia amplificata (nessun cuscinetto) | **ALTA** | Immediato (dato pubblico giornaliero) | 2024: stock ICE ai minimi decennali durante lo squeeze |
| **Speculazione / CTA / hedge fund** | Il mercato è piccolo (OI ~250k contratti = frazione del crude): i flussi sistematici trend-following lo spingono oltre i fondamentali in entrambe le direzioni; poi si va in *liquidation cascade* | **ALTA nei estremi** | Giorni-settimane | Ott 2024 −37% in 120g (misurato): pura de-leverage; oggi net short −20k = affollamento opposto |
| **Domanda (grindings)** | I *grindings* trimestrali (Europa/Asia/Nordamerica) sono il proxy della domanda; la domanda di cioccolato è anelastica ma non infinita: a $10k+ è partita la demand destruction (ricette riformulate, meno % cacao) | **MEDIA** | Trimestri | 2025: grindings in calo → contributo al −48% annuale (misurato) |
| **Dollaro (DXY)** | Cacao quotato in USD: dollaro forte = cacao più caro per i consumatori non-USD → pressione ribassista. Correlazione misurata: **−0.18 settimanale** (debole!) | **BASSA-MEDIA** | Contemporaneo | Il rally 2024 ha ignorato completamente il dollaro |
| **Tassi d'interesse** | Effetto indiretto: costo del carry per le trade house (finanziare inventory a tassi alti = meno scorte detenute → mercato più nervoso); tassi alti 2023-24 hanno amplificato lo squeeze | **BASSA-MEDIA** | Mesi | Correlazione T10Y misurata: +0.02 (nulla direzionalmente) |
| **Energia/trasporti/fertilizzanti** | Costi input (fertilizzante = gas) e noli; effetto sui margini dei coltivatori più che sul prezzo di borsa | **BASSA** | 6-18 mesi | 2022: fertilizzanti +100% → contributo al deficit 2023 |
| **Guerre/geopolitica locale** | Guerra civile ivoriana = blocco export | **ALTA quando accade** | Immediato | 2002-03: guerra civile CIV → +80% in 120g (misurato); 2011 crisi post-elettorale → export ban di Ouattara |
| **Inflazione** | Il cacao NON è un inflation hedge sistematico (correlazioni quasi nulle con macro) — muove per fattori propri | **BASSA** | — | 2024: rally in anno di disinflazione |

**Sintesi:** la volatilità del cacao è **concentrazione geografica × rigidità dell'offerta × mercato piccolo**. È un mercato dove i fondamentali agricoli locali (meteo di due Paesi africani) contano più di tutta la macro globale — la tabella delle correlazioni (sez. 7) lo dimostra numericamente.

---

## 3. Analisi storica (2000-2026, misurata sui dati)

**Top 5 rally (variazione rolling su 120 giorni di borsa):**

| Data picco finestra | Movimento | Causa |
|---|---|---|
| **19 apr 2024** | **+212%** | La madre di tutti gli squeeze: deficit CIV/Ghana (El Niño + black pod + CSSV + sottoinvestimento), stock ICE ai minimi, COCOBOD che rolla i forward, short commercial intrappolati. Da ~$4.000 a $12.565 |
| 11 mar 2002 | +80% | Instabilità ivoriana pre-guerra civile + ciclo di deficit; culmina col colpo di stato di settembre 2002 |
| 19 dic 2024 | +65% | Seconda gamba della bolla: raccolto principale 2024/25 ancora deludente dopo la correzione di ottobre |
| 18 mag 2001 | +60% | Ripresa dai minimi ventennali ($674!), primi segnali di deficit |
| 23 giu 2008 | +57% | Superciclo commodity generalizzato (petrolio a $147) |

**Top 5 crolli:**

| Data | Movimento | Causa |
|---|---|---|
| **27 feb 2026** | **−62%** | Sgonfiamento della bolla: risposta dell'offerta (nuovi impianti, cura degli alberi ai prezzi record), demand destruction, ritorno del surplus — *inferenza dai dati, evento post-cutoff* |
| 28 lug 2003 | −40% | Normalizzazione post-guerra civile: risk premium rientrato |
| 13 feb 2017 | −39% | Raccolto record dell'Africa Occidentale 2016/17 → surplus massiccio |
| 17 lug 2025 | −37% | Prosecuzione del bear market post-bolla |
| 10 ott 2024 | −37% | Correzione violenta DENTRO la bolla: liquidazione speculativa di massa (il mercato salì di nuovo subito dopo — trappola per entrambe le direzioni) |

**Anni estremi:** 2024 **+178%**, 2001 +73%, 2023 +61%, 2002 +54% ↔ 2025 **−48%**, 2016 −34%, 2011 −31%. **Max drawdown storico: −78%. Drawdown attuale: −56%.**

**Cosa si ripete (pattern storico dei supercicli):** deficit pluriennale da sottoinvestimento → prezzo esplode (1-2 anni) → i prezzi record finanziano replanting/cura + demand destruction → surplus → bear market pluriennale (−40/−70%) → prezzi bassi → nuovo sottoinvestimento. Ciclo completo: **6-10 anni** (boom 2002→bust 2003-05; boom 2008-10→bust 2011-13; mini-ciclo 2015-17; boom 2023-24→bust 2025-oggi). **Siamo oggi nella fase bust, a ~18 mesi dal picco.**

---

## 4. Ciclicità (misurata su 26-27 osservazioni per mese)

**Stagionalità mensile (rendimento medio, win rate, vol):**

| Mese | Ret. medio | Win | Vol | Lettura agronomica |
|---|---|---|---|---|
| Gen | +1.91% | 50% | 12.1% | Pieno arrivo main crop, ma domanda grindings |
| Feb | +2.25% | 59% | 13.0% | Fine main crop; primi timori sul mid-crop |
| Mar | +0.65% | 59% | 14.0% | Mese più volatile: incertezza mid-crop |
| **Apr** | **+3.02%** | **67%** | 8.8% | **Il mese statisticamente più forte**: mid-crop risk premium |
| Mag | −1.40% | 48% | 9.1% | Mid-crop arriva: pressione |
| Giu | +2.15% | 59% | 9.4% | Weather market: fioritura del main crop successivo |
| Lug | +1.06% | 59% | 8.9% | Weather market |
| Ago | +1.72% | 54% | 9.3% | Attesa pod counting |
| Set | −0.75% | 54% | 9.9% | Vigilia raccolto |
| **Ott** | **−2.80%** | **35%** | 7.0% | **Il mese peggiore in assoluto**: apre la stagione, main crop inonda i porti |
| **Nov** | **+3.42%** | 54% | 13.1% | Rimbalzo post-pressione + prime stime deficit |
| Dic | +2.59% | 58% | 9.6% | Domanda festiva + posizionamento nuovo anno |

**I tre segnali stagionali forti:** (1) **ottobre corto** — unico mese sotto il 50% di win rate in modo netto (35%), meccanismo chiaro (arrivo del raccolto); (2) **aprile lungo** — 67% win col miglior rapporto rendimento/vol; (3) **novembre-dicembre lunghi** ma con vol alta (novembre è anche il mese più dispersivo: +3.42% medio con 13% di vol = anni molto buoni e molto cattivi).

**Settimanale:** martedì +0.14%/mercoledì +0.12% vs lunedì/venerdì negativi — effetto debole, non operativo da solo (coerente col fatto che gli stock ICE e i report escono infrasettimana).

**Ciclo del raccolto (il metronomo del mercato):** main crop ottobre-marzo (~80% della produzione CIV), mid-crop aprile-settembre. I *pod counting* di agosto-settembre e le stime di arrivo ai porti (ott-dic) sono gli eventi informativi ricorrenti. **Ciclo pluriennale:** 6-10 anni come da sez. 3 (guidato dall'elasticità ritardata dell'offerta — 3-4 anni perché un albero produca).

---

## 5. Analisi quantitativa (risultati misurati e interpretazione)

| Metrica | Valore | Interpretazione operativa |
|---|---|---|
| **Autocorrelazione daily (lag 1-60)** | −0.007 … +0.016 (tutte ≈ 0) | La direzione di domani NON si prevede dai rendimenti passati: niente edge da momentum/reversal daily puro |
| **Vol clustering (|r| lag1)** | **+0.145** (lag5 +0.128) | La VOLATILITÀ sì che si prevede: giorni agitati seguono giorni agitati → GARCH funziona, il sizing va adattato al regime |
| **Persistenza regime vol alto** | **P(alto→alto) = 95%** | Un regime di vol non finisce domani: gli stop vanno dimensionati per il regime, non per la media storica |
| **Distribuzione** | vol 2.2%/g (35% annua), skew −0.27, kurtosis excess 6.1 | Code grasse asimmetriche: il rischio di gap contro è reale e maggiore a sinistra |
| **Fat tails** | giorni \|r\|>8%: **25× la frequenza gaussiana** (46 osservati vs 1.8 attesi); peggior giorno **−22.9%** | Mai stop mentali, mai size da "asset normale": un −8/−20% in un giorno è un evento che ACCADE |
| **Hurst (intero campione)** | 0.456 | Leggermente mean-reverting/random sull'intera storia |
| **Hurst (ultimi 3 anni)** | **0.541** | Il superciclo ha reso il processo TRENDING: nei regimi di squeeze il momentum paga |
| **Half-life mean reversion** | 637 giorni storico; **117 giorni ultimi 3y** | Gli shock di prezzo persistono per mesi/anni: il cacao non "torna al prezzo di ieri", torna al costo marginale in 1-3 anni. La MR è di livello (pluriennale), non tattica |
| **Regime switching** | Confermato: terzili vol <25% / 25-33% / >33%; oggi **76%** | Siamo fuori scala: il regime attuale è il più estremo della storia recente — ogni parametro operativo va scalato |

**Sintesi quantitativa:** il cacao daily è **imprevedibile in direzione ma prevedibile in volatilità e regime**. L'edge non è "indovinare domani" ma: (a) posizionarsi con i fondamentali nella direzione del ciclo, (b) sfruttare la stagionalità come tilt, (c) dimensionare col regime di vol, (d) sopravvivere alle code.

---

## 6. Pattern ricorrenti

| Pattern | Frequenza | Affidabilità | Note operative |
|---|---|---|---|
| **Spike da notizia (meteo/politica CIV-Ghana)** | 5-10/anno | Alta come evento, bassa come direzione post-spike | I gap da notizia raramente ritracciano subito (half-life lunga): inseguire lo spike il giorno dopo ha battuto il fade nel 2023-24; nel regime attuale (bear) vale il contrario |
| **Trend acceleration (parabolica)** | 1 per superciclo | Alta finché dura, uscita impossibile da temporizzare | Hurst>0.5 nei regimi trending: piramidare con trailing, MAI contro-trend nel mezzo |
| **Falso breakout in range** | Frequente nei regimi calmi (vol<25%) | Breakout daily in bassa vol: ~50% falliti (stima) | In bassa vol il cacao rangeggia: fade degli estremi con l'ATR; in alta vol l'opposto |
| **Liquidation cascade** | 1-3 per anno di regime estremo | Riconoscibile: −10/−20% in giorni con OI in crollo | Ott 2024 e feb 2026 (misurati): quando l'OI crolla insieme al prezzo è de-leverage, non fondamentali → rimbalzo tecnico probabile ma violento |
| **Ottobre corto stagionale** | Annuale | 65% (win rate 35% del mese) | L'unico pattern calendario abbastanza forte da essere un filtro |
| **Consolidamento post-crollo** | Dopo ogni bust | — | Range pluriennale a ridosso del costo di produzione ($2.200-3.000 storici; oggi il floor è più alto per LID e inflazione input) |

---

## 7. Correlazioni (rendimenti settimanali, n≈1.350-1.384)

| Asset | Contemporanea | X→cacao (lag 1 sett.) | Lettura |
|---|---|---|---|
| Caffè | **+0.19** | 0.00 | La più alta: complesso softs condiviso (clima tropicale, flussi CTA) — ma comunque debole |
| DXY | **−0.18** | +0.01 | Direzione attesa, intensità modesta |
| Oro | +0.12 | −0.02 | Nulla di utile |
| WTI | +0.12 | 0.00 | Nulla |
| S&P 500 | +0.12 | +0.01 | Non è un asset risk-on/risk-off |
| Rame | +0.11 | +0.01 | Nulla |
| Zucchero | +0.10 | +0.02 | Sorprendentemente bassa per un "cugino" soft |
| VIX | −0.10 | −0.03 | Nulla |
| T10Y | +0.02 | +0.02 | Zero |

**Il risultato più importante della sezione: NESSUNA correlazione ritardata utilizzabile** (tutte ≤|0.03|). Gli altri mercati **non anticipano il cacao**. Le valute africane (XOF è ancorato all'euro, il cedi ghanese GHS è poco tradabile) non aggiungono segnale — semmai il cedi debole aumenta l'incentivo allo smuggling Ghana→CIV, un fattore fondamentale, non di prezzo. Nei regimi di liquidation cascade la correlazione col complesso commodity sale temporaneamente (tutti vendono tutto), poi torna a zero. **Conseguenza per il modello: il cross-asset layer vale poco sul cacao; contano meteo, raccolto, scorte, COT.**

---

## 8. Indicatori anticipatori (con fonti gratuite)

| Indicatore | Fonte gratuita | Frequenza | Potere predittivo |
|---|---|---|---|
| **ENSO (El Niño/La Niña)** | NOAA CPC (`cpc.ncep.noaa.gov`), indice ONI; IRI forecast plume | Settimanale/mensile | **ALTO a 6-12 mesi**: il migliore leading indicator dell'offerta |
| **Meteo Africa Occidentale** (precipitazioni/Harmattan Dic-Feb) | NOAA CPC Africa desk, Open-Meteo API (gratis), TAMSAT | Giornaliera | **ALTO a 3-6 mesi** durante fioritura/sviluppo pod |
| **COT Report (cacao 073732)** | CFTC via OpenBB (già nel sistema) | Settimanale (ven, dati mar) | **MEDIO — ma NON come indicatore contrarian** (vedi correzione §13.4): sui dati, spec net LONG estremo → +16,0% a 6 mesi (59% win); spec net SHORT estremo → −1,7% a 6 mesi (41% win). Sul cacao gli speculatori CONFERMANO il trend, non lo invertono |
| **Stock certificati ICE** | ICE Report Center (`ice.com/report-center`, sezione Cocoa certified stocks) | Giornaliera | **ALTO**: scorte ai minimi = amplificatore di ogni notizia |
| **Arrivi ai porti CIV** (cumulative arrivals) | Pubblicati da Reuters/Bloomberg citando esportatori; aggregati su siti di settore | Settimanale in stagione | **ALTO ott-mar**: il confronto arrivi vs anno precedente è IL dato del raccolto |
| **Grindings trimestrali** (ECA Europa, CAA Asia, NCA Nordamerica) | Comunicati delle associazioni (ECA: `eurococoa.com`) | Trimestrale | **MEDIO**: proxy domanda, mercato reagisce alle sorprese |
| **Report ICCO** (Quarterly Bulletin, surplus/deficit) | `icco.org` — sintesi gratuite | Trimestrale | **MEDIO**: autorevole ma in ritardo sul mercato |
| **NDVI / satelliti** (verde vegetazione CIV/Ghana) | NASA MODIS/Copernicus Sentinel (gratis via Google Earth Engine) | 8-16 giorni | **MEDIO, sofisticato**: anticipa la resa; richiede pipeline dedicata |
| **Farmgate price / politiche CCC-COCOBOD** | Annunci stampa (Reuters Africa) — via news engine | Eventi | **MEDIO a 1-3 anni** (incentivo a piantare/curare) |
| **EUDR (regolamento UE deforestazione)** | Notizie UE | Eventi | **MEDIO**: compliance = attrito sull'offerta verso l'UE |
| Fertilizzanti / Baltic Dry | World Bank Pink Sheet (mensile, gratis) / `balticexchange.com` | Mensile | BASSO: effetto lento sui margini |
| Prezzo | — | — | Come da sez. 5: il prezzo stesso NON si anticipa da solo sul daily |

---

## 9. Modelli previsionali — confronto onesto

| Modello | Pro | Contro | Quando funziona sul cacao | Difficoltà |
|---|---|---|---|---|
| Regressione lineare/multivariata | Interpretabile, poca varianza | Relazioni non lineari perse | Baseline su feature fondamentali (arrivi, stock, ENSO) a orizzonte 1-3 mesi | Bassa |
| **ARIMA/SARIMA** | Standard, stagionalità gestita | Autocorr daily ≈ 0 (misurata) → poco da modellare; SARIMA cattura il mensile ma con 26 anni di dati mensili il campione è piccolo | Orizzonte mensile, come benchmark | Bassa |
| **GARCH** | **Vol clustering fortissimo (misurato: 0.145)** → prevede bene la VOLATILITÀ | Non prevede la direzione | **Sempre — per sizing e stop, non per direzione. Il modello più "onesto" per il cacao** | Bassa-media |
| Prophet | Facile, trend+stagionalità | Troppo liscio per un asset a code grasse; sottostima i salti | Solo esplorazione | Bassa |
| VAR | Multivariato con esogene | Le correlazioni cross-asset misurate sono ≈0 → VAR su asset finanziari inutile; utile con variabili FONDAMENTALI (stock ICE, arrivi) | Con dati fondamentali trimestrali/settimanali | Media |
| **HMM (regime switching)** | **Regimi di vol persistenti (P=95%) misurati** → HMM li identifica bene | Non dà direzione, dà lo stato | **Filtro di regime per accendere/spegnere strategie** — già presente nel tuo `quant/` | Media |
| Random Forest / XGBoost / LightGBM / CatBoost | Non-lineari, feature miste (meteo+COT+stagionalità+tecnica), feature importance leggibile | Overfitting facile su 6.600 punti; richiede walk-forward severo | **Il miglior compromesso per direzione settimanale/mensile** con feature fondamentali. XGBoost ≈ LightGBM ≈ CatBoost (differenze marginali) | Media |
| SVR | Robusto su piccoli dataset | Tuning fragile, poco interpretabile | Raramente superiore ai tree | Media |
| LSTM / GRU | Sequenze lunghe | **6.600 barre sono POCHE per il deep learning**; sul daily non c'è segnale da estrarre (autocorr 0); overfitting quasi garantito | Solo con dati intraday abbondanti + feature esogene | Alta |
| Transformer / TFT / N-BEATS | Stato dell'arte su serie con molta struttura | Stessi limiti dei precedenti amplificati: fame di dati, il TFT brilla con MOLTE covariate note nel futuro (che qui sono poche: calendario e stagionalità) | TFT interessante SE hai pipeline meteo/NDVI ricca; altrimenti no | Alta |

**Accuratezza tipica realistica (direzionale):** su orizzonte 1 settimana chiunque dichiari >55-58% out-of-sample sul cacao va guardato con sospetto; il valore non è la % di hit ma il **payoff asimmetrico** (prendere i trend grossi, evitare le code contro).

---

## 10. Migliore approccio operativo — architettura

**Filosofia (dai numeri):** direzione daily ≈ imprevedibile → si lavora su **tre orizzonti**: regime (HMM/vol), fondamentale (settimanale-mensile), evento (news + calendario raccolto).

```
DATI (frequenza)
├── Prezzo/volume ICE via CC=F (daily) + OI
├── COT cacao 073732 (settimanale)            ← già nel sistema
├── Stock certificati ICE (daily, scrape)
├── Arrivi porti CIV (settimanale, da news)   ← news engine
├── ENSO/ONI NOAA (mensile) + meteo West Africa (daily, Open-Meteo API)
├── Grindings (trimestrale) + report ICCO
└── News: regole dedicate cacao (meteo, malattie, CCC/COCOBOD, EUDR, porti)

FEATURE ENGINEERING
├── Tecniche: ret 1/5/20/60g, ATR%, dist. da MA50/200, breakout flags
├── Stagionali: mese one-hot (ott!), fase raccolto (main/mid), settimana della stagione
├── Fondamentali: Δstock ICE 4w, arrivi vs anno prec. (quando disponibili), ENSO index e Δ
├── Posizionamento: net spec, Δnet 4w, %long (estremi = contrarian)
└── Vol: GARCH(1,1) forecast, regime HMM (2-3 stati)

MODELLI (ensemble a 3 gambe)
├── Gamba 1 — REGIME: HMM su vol/ret → trending/ranging/crisis (accende le altre)
├── Gamba 2 — DIREZIONE: LightGBM classificazione ret 5g e 20g avanti
│              (walk-forward: train 8y → test 1y, rolling; embargo 20g anti-leakage)
└── Gamba 3 — VOL: GARCH per sizing e stop (target vol costante)

VALIDAZIONE: walk-forward annuale; metriche = direzionale % + PROFIT FACTOR
(la MAE/RMSE sul prezzo è quasi irrilevante per il trading); Sharpe della strategia;
max DD. Anti-overfitting: max ~20 feature, early stopping, purged CV, e la regola
d'oro: se il backtest è troppo bello, è rotto.
```

**Integrazione nel TUO sistema (fatta in questa sessione):** cacao aggiunto all'universo (`COCOA`), COT 073732 collegato, regole news dedicate nel news engine (meteo Africa Occidentale, El Niño, black pod/swollen shoot, CCC/COCOBOD, arrivi ai porti, EUDR, surplus/deficit ICCO), stagionalità ottobre/aprile annotata. Il decision engine lo tratta come l'oro: layer news + tech + COT (+ stagionalità come nota), CON un avvertimento di sizing (vedi sotto).

---

## 11. Strategia pratica (per il TUO conto: €400, IC Markets)

**⚠️ Prima la verità sul sizing:** con vol attuale 76% annua (~4.8% al giorno ≈ $270/t di ATR), se il CFD IC Markets vale ~$1/punto/lotto con lotto minimo 1, uno stop a 1.2×ATR rischia ~€300 = 75% del conto → **il risk manager lo rifiuterà, correttamente**. Il cacao diventa tradabile per te solo se: (a) le specifiche MT5 mostrano un contratto/lotto minimo più piccolo (verifica: tasto dx su "Cocoa" → Specifiche), oppure (b) la vol rientra sotto ~35% annua. Fino ad allora il sistema lo **monitora e genera segnali informativi**, non ticket.

**La strategia (quando sizable, o per capitale maggiore):**

- **Regime filter (obbligatorio):** niente posizioni nuove se vol 21g > 50% annua salvo segnale evento forte; in vol > 50% solo trade da liquidation cascade.
- **Ingresso long stagionale-fondamentale:** finestra **fine marzo-aprile** (mese +3.02%, 67% win) SE stock ICE in calo e COT non estremamente long → long con stop 1.2×ATR, ladder 5 TP standard del sistema.
- **Ingresso short stagionale:** **fine settembre-inizio ottobre** (ottobre 35% win) SE arrivi ai porti sopra l'anno precedente e COT net long → short.
- **Trade contrarian da posizionamento (setup di OGGI):** net spec short estremo (−20/−29k) + prezzo −56% dal picco + ricoperture iniziate + OI in risalita = le condizioni classiche del **bottom-fishing long** — MA si entra solo su conferma tecnica (recupero della MA50 daily, oggi lontana) o su catalyst news (deficit inatteso), mai su anticipazione.
- **Gestione:** stop SEMPRE reale (mai mentale: code −22.9% documentate), a TP1 stop a breakeven (regola del sistema), rischio max 1.8-2%/trade, mai overnight su weekend con report ICCO/pod counting attesi, uscita totale se il regime HMM passa a "crisis" contro la posizione.
- **Da monitorare ogni giorno:** stock ICE, meteo CIV/Ghana (Dic-Feb: Harmattan; Mag-Lug: piogge fioritura), net COT del venerdì, prezzo vs MA50/200, e le news del motore (regole cacao ora attive).

---

## 12. Conclusioni

**I 10 insight più importanti (tutti misurati o verificati):**

1. **La direzione daily è imprevedibile** (autocorr ≈ 0 su tutti i lag): chi vende "segnali giornalieri sul cacao" da price action pura vende rumore.
2. **La volatilità è molto prevedibile** (clustering 0.145, persistenza regime 95%): GARCH/regime è l'unico "gratis" statistico del mercato.
3. **Ottobre è il pattern calendario più forte** (35% win, −2.8% medio, meccanismo agronomico chiaro); aprile il migliore al rialzo (67%, +3.0%).
4. **Le code sono 25× quelle gaussiane** (|r|>8%): la sopravvivenza viene prima della previsione — sizing e stop reali non sono negoziabili.
5. **Il cacao è idiosincratico**: correlazioni cross-asset ≤|0.19| e lag nulli → DXY, oro, S&P, tassi NON lo anticipano. Il modello va costruito su meteo/raccolto/scorte/COT, non sulla macro.
6. **Half-life 117-637 giorni**: gli shock persistono per mesi/anni — la mean reversion è di ciclo, non di settimana. Non si "fadeano" i movimenti fondamentali.
7. **Hurst cambia col regime** (0.46 storico → 0.54 nel superciclo): trend-following funziona SOLO nei regimi di squeeze; nei regimi calmi il mercato rangeggia.
8. **Il superciclo 6-10 anni è il pattern dominante** (offerta che risponde con 3-4 anni di ritardo): siamo nella fase bust, −56% dal picco, come da copione 2003, 2011, 2017.
9. **Il COT agli estremi è un segnale reale — ma nella direzione OPPOSTA a quella che avevo scritto.** Il test del 13/08 (§13.4) smentisce la lettura contrarian: spec net long estremo → **+16,0% a 6 mesi** (59% win), spec net short estremo → **−1,7% a 6 mesi** (41% win, sotto il +5,7% di baseline). Sul cacao gli speculatori hanno storicamente ragione. Oggi il net è al 17° percentile (zona short): storicamente un contesto di rendimenti **sotto la media**, nonostante il rally in corso.
10. **Due Paesi = metà dell'offerta**: ogni modello che non abbia il meteo di Costa d'Avorio e Ghana come feature primaria sta ignorando il fattore #1.

**Massimo potere predittivo:** ENSO/meteo (6-12 mesi) → arrivi ai porti + stock ICE (settimane) → COT agli estremi (settimane) → stagionalità ott/apr (giorni-settimane) → GARCH per la vol (giorni).
**Rumore:** correlazioni cross-asset, notizie macro USA, price action daily pura, forum/sentiment retail.

**Ranking tecniche previsionali (dalla migliore):**
1. **GARCH + regime HMM** — prevede ciò che è davvero prevedibile (vol/regime); base di tutto
2. **Gradient boosting (LightGBM/XGBoost) su feature fondamentali+stagionali+COT** — direzione settimanale/mensile, interpretabile, dati sufficienti
3. **Modello fondamentale strutturale** (bilancio offerta/domanda ICCO + arrivi) — lento ma è ciò che muove i supercicli
4. **Stagionalità pura** — semplice, robusta, ma solo 2-3 finestre all'anno
5. **SARIMA/regressioni** — benchmark onesti, edge minimo
6. **Prophet** — inadatto alle code del cacao
7. **LSTM/GRU/Transformer/TFT/N-BEATS** — ultimi NON perché deboli in assoluto, ma perché 6.600 barre daily con segnale direzionale nullo sono il peggior terreno possibile per il deep learning: overfitting quasi certo, zero interpretabilità. Diventerebbero interessanti solo con anni di dati intraday + pipeline satellitare/meteo ricca.

**Punteggio di potenziale predittivo (0-100%):**

| Approccio | Score | Perché |
|---|---|---|
| **Analisi fondamentale (meteo/raccolto/scorte)** | **75%** | Muove davvero il prezzo, leading di mesi; limite: dati frammentari e già parzialmente prezzati dai professionisti del fisico |
| **Modelli statistici (GARCH/HMM/regressioni)** | **60%** | Eccellenti su vol e regime (il prevedibile), quasi nulli sulla direzione daily |
| **Stagionalità** | **55%** | 2-3 pattern reali e meccanicamente spiegabili (ott/apr/nov), ma n=26 → intervalli di confidenza larghi; da usare come tilt, mai da sola |
| **Machine learning (boosting su feature fondamentali)** | **50%** | Valore = quello delle feature che gli dai; con sole feature di prezzo scende a ~30% |
| **Analisi tecnica** | **40%** | Utile per timing/gestione (livelli, ATR, trend filter) dentro una view fondamentale; da sola, su un asset con autocorr zero e code enormi, perde |
| **Deep learning** | **25%** | Mismatch struttura-dati: troppa capacità, troppo pochi dati, segnale daily nullo. Il punteggio sale (→45-50%) solo con pipeline dati satellitare/meteo/intraday seria |

**Bottom line per il sistema:** il cacao è ora nell'universo con news dedicate e COT; genererà segnali quando meteo/raccolto/posizionamento convergono — ma con l'avvertenza di sizing esplicita finché la volatilità resta in regime estremo. Il vero edge replicabile: **essere corti a ottobre, lunghi ad aprile, seguire gli squeeze quando partono, e non farsi mai trovare senza stop.**

---

## 13. Setup algoritmico e backtest (13 agosto 2026)

Dalla teoria alla regola operativa. Tutto quanto segue è **misurato**, non ipotizzato: motore event-driven, stop colpito prima del target nello stesso giorno (ipotesi conservativa), costi $10/t round-trip (spread CFD IC Markets ~8 + slippage), rischio 2% per trade.

### 13.1 Cosa NON funziona (il risultato più utile)

Ho testato per primo l'approccio ovvio — il trend following — in **60 combinazioni** di segnale e parametri di uscita:

| Segnale | Stop/trailing testati | Hold testati | Profit factor |
|---|---|---|---|
| Breakout Donchian 55 | 2/3, 2/5, 3/6, 2/8, 3/10 ATR | 60, 120, 250, 500 giorni | **0,69 – 1,07** |
| Donchian 55 + filtro MA200 | idem | idem | **0,69 – 1,04** |
| Donchian 20 + filtro MA200 | idem | idem | **0,70 – 0,96** |
| Incrocio MA50/200 | 2/3 ATR | 60 | 0,95 |
| Pullback in trend | 2/3 ATR | 60 | 0,81 |
| Stagionale ott-short / apr-long | 2/3 ATR | 60 | 0,76 |

**Nessuna configurazione supera 1,07.** Il trend-following tecnico sul cacao non ha edge — esattamente ciò che prevedeva l'autocorrelazione ≈ 0 del §5. Anche il pattern stagionale di ottobre, statisticamente reale, **non sopravvive ai costi e agli stop**: è un'inclinazione della distribuzione, non un trade.

Da notare: il buy & hold semplice rende +7,8% annuo composto nel periodo. Battere il buy & hold sul cacao è difficile.

### 13.2 Cosa funziona: comprare i cali dentro il trend, solo long

L'unica regola sopravvissuta:

```
LONG-ONLY
├─ trigger  : RSI(14) < 30            (eccesso di ipervenduto)
├─ filtro   : prezzo > MA200          (si compra il calo, non il crollo)
├─ stop     : 3 × ATR(14)
├─ trailing : 6 × ATR dal massimo
└─ uscita   : trailing stop o 60 giorni
```

**Risultati 2000-2026:** 44 trade (~2/anno) · win rate 45,5% · **profit factor 3,01** · +0,90R medio per trade · +39,7R totali · durata media 39 giorni · max drawdown della strategia −13,7%.

**Perché solo long — e non è una scelta arbitraria.** Sugli stessi dati il lato short misura PF 0,91 (perdente) contro 2,95-3,01 del lato long. La ragione è strutturale, non statistica: al ribasso esiste un pavimento (il costo di produzione: sotto una certa soglia i coltivatori smettono di vendere e i governi tagliano i prezzi al coltivatore, come a febbraio), al rialzo no — un albero nuovo produce dopo 3-4 anni, quindi l'offerta **non può** rispondere. È la stessa asimmetria che ha prodotto il +212% del 2024 e il +106% di quest'anno.

### 13.3 Validazione (la parte che smonta le strategie finte)

**Robustezza parametrica** — la firma di un edge vero è che non dipende dalla soglia esatta:

| RSI | filtro | n | win% | PF |
|---|---|---|---|---|
| <25 | MA200 | 32 | 56,2% | 2,34 |
| <30 | MA200 | 50 | 48,0% | **2,61** |
| <35 | MA200 | 66 | 45,5% | 1,93 |
| <40 | MA200 | 90 | 44,4% | 1,58 |
| <30 | nessuno | 146 | 45,2% | 1,54 |
| <35 | MA50 | 31 | 41,9% | 2,42 |

Tutte sopra 1. Nessun burrone tra un parametro e il successivo.

**Out-of-sample** — regola fissata sui dati 2000-2015, testata su 2016-2026 (mai vista in fase di design):

| Configurazione | In-sample 2000-2015 | Out-of-sample 2016-2026 |
|---|---|---|
| stop 3 / trail 6 / hold 60 | PF 1,77 (n=28) | **PF 5,19 (n=16)** |
| stop 2,5 / trail 5 / hold 40 | PF 2,38 (n=31) | **PF 3,15 (n=18)** |

Il fuori campione è migliore del dentro campione: la regola non è stata cucita sui dati.

**Costi:** regge fino a **$50/t** round-trip (PF 1,69). Il costo reale sul CFD è ~$10.

**Bootstrap, 5.000 storie alternative** (44 trade estratti con reinserimento): equity finale mediana +81%, 5° percentile −0,2%, 95° percentile +362%, **probabilità di chiudere in perdita 5%**, drawdown mediano −10%.

### 13.4 Il segnale COT: correzione a quanto scritto a luglio

Nel §8 avevo classificato il COT come indicatore **contrarian**. Il test lo smentisce. Rendimenti futuri per regime di posizionamento speculativo (percentile a 3 anni, 1.585 settimane):

| Regime COT | n | +1 mese | +3 mesi | +6 mesi | win 3m |
|---|---|---|---|---|---|
| **Short estremo (<10° pct)** | 257 | +0,9% | +2,2% | **−1,7%** | 41% |
| Short (10-25°) | 195 | −0,1% | +0,6% | −2,0% | 38% |
| Neutro (25-75°) | 689 | +1,6% | +2,1% | +3,6% | 45% |
| Long (75-90°) | 185 | +2,2% | +8,2% | +13,4% | 46% |
| **Long estremo (>90° pct)** | 259 | −0,1% | +5,2% | **+16,0%** | **59%** |
| *baseline* | 1.585 | +1,1% | +3,3% | +5,7% | 45% |

Sul cacao **gli speculatori hanno storicamente ragione**: il posizionamento estremo long precede i rendimenti migliori, quello short i peggiori. Il COT va usato come *conferma di trend*, non come segnale di inversione. Questo ribalta la lettura che avevo dato del setup attuale.

### 13.5 Il limite da conoscere prima di usarla

**Il 73% del profitto storico viene da UN solo trade** (dicembre 2023 → marzo 2024, +28,8R: la bolla).

| Escludendo i migliori | R totale | R/trade | PF |
|---|---|---|---|
| — (tutti i 44) | +39,7 | +0,90 | 3,01 |
| i primi 1 | +10,9 | +0,25 | 1,49 |
| i primi 3 | +3,0 | +0,07 | 1,14 |
| **i primi 5** | **−3,1** | −0,08 | **0,84** |

E per decennio non è affatto uniforme: 2000-05 PF 4,51 · 2005-10 PF 4,73 · **2010-15 PF 0,73** · **2015-20 PF 0,35** · 2020-26 PF 4,13. Ci sono stati **due quinquenni consecutivi in perdita**.

Questa è una strategia a coda grassa: molte perdite piccole (−1R) in attesa dell'evento raro che paga tutto. È coerente con ciò che il cacao *è* (§5: code 25× la gaussiana), ma richiede la disciplina di incassare 10 stop di fila senza cambiare regola.

**Corollario operativo importante:** la ladder a 5 take profit del sistema (1R/1,5R/2R/3R/4R) **rovina questa strategia** — con un cap a 4R il risultato passa da +39,7R a +14,8R. Sul cacao si usa il trailing stop e si lascia correre.

### 13.6 Stato al 13 agosto 2026 e sizing reale

- prezzo $5.754 · RSI **59** · MA200 $4.575 · ATR $337
- filtro di trend: ✅ prezzo sopra MA200 → **setup ARMATO**
- trigger: ❌ serve RSI < 30 → **nessun ingresso adesso, si aspetta**
- frequenza attesa del trigger: RSI<30 si è verificato nel 17% dei giorni negli ultimi 2 anni

**E qui arriva il problema pratico:** con ATR a $337 lo stop a 3 ATR vale **$1.012/t**. Sul lotto minimo (0,01) sono ~$101 di rischio = **23% di un conto da €400**. Il risk manager rifiuta, correttamente. Serve una di queste condizioni: volatilità che rientra sotto ~25% annua (oggi 66%), specifiche MT5 con contratto più piccolo di quello stimato, o un capitale di almeno €2.000-2.500 per rispettare il 2% per trade.

Fino ad allora il sistema **monitora e segnala, non emette ticket**.

---
*Metodologia: tutti i valori numerici (stagionalità, autocorrelazioni, Hurst, half-life, code, correlazioni, rally/crolli, COT, backtest) sono calcolati su dati reali ICE CC=F nelle sessioni del 14/07/2026 e 13/08/2026. Le cause fondamentali del §0 provengono dalle fonti citate in fondo. Backtest riproducibile con `python cocoa_setup.py --backtest`. Questo documento è ricerca personale, non consulenza finanziaria.*

**Fonti §0:** [ConfectioneryNews — Cocoa prices collapse following record highs](https://www.confectionerynews.com/Article/2026/02/13/cocoa-prices-collapse-following-record-highs/) · [Yahoo Finance — Cocoa Prices Plunge as Global Supplies Build](https://finance.yahoo.com/news/cocoa-prices-plunge-global-supplies-170426987.html) · [StoneX — Cocoa Market Faces Life After Crisis](https://www.stonex.com/en/insights/cocoa-market-faces-life-after-crisis/) · [Barchart — Cocoa Prices Surge on Ghana Crop Worries](https://www.barchart.com/story/news/3618231/cocoa-prices-surge-on-ghana-crop-worries) · [Capital.com — Cocoa Price Forecast / Ghana-Ivory Coast Pricing Deal](https://capital.com/en-eu/analysis/cocoa-price-forecast) · [RioTimes — Cocoa Pricing: Ghana and Ivory Coast Align in 2026](https://www.riotimesonline.com/ghana-ivory-coast-cocoa-pricing-2026/) · [Wikifarmer — El Niño 2026 e impatto sul cacao](https://wikifarmer.com/library/en/article/el-nino-2026-cocoa-commodity-impact)
