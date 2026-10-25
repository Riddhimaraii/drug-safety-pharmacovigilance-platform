# Drug Safety & Pharmacovigilance Review

_Generated 24 Oct 2026 from FDA FAERS quarterly data: 2020Q4. Database built 2026-10-24 11:08._

> **Purpose.** Summarise reporting patterns in spontaneous adverse-event reports and list drug-reaction pairs and records that deserve **human review**. Nothing here shows that a drug causes a reaction.

## 1. Dataset at a glance

- **436,148** unique cases (latest version of each case), received by FDA between **2020-08-27** and **2020-12-31**; reaction terms: **12,293** MedDRA preferred terms; drugs (primary suspect, standardised to active ingredient): **2,428**.
- **64.6%** of cases carry at least one serious outcome (44,785 deaths = 10.3%; 97,124 hospitalisations = 22.3%).
- Patients: 59% female among cases with known sex (358,133 of 436,148); median age 59 years (39% aged 65+, age known for 53% of cases).
- Reporters: Consumer 45%, Unknown 23%, Physician 20%, Pharmacist 7%, Lawyer 6%.

## 2. Key reporting patterns

- **Volume:** 30,520-40,925 reports per full week (median 32,212); first/last weeks of an extract are partial and are ignored for trend checks.
- **Most-reported primary-suspect drugs**

| drug | reports | serious_% | fatal_% | median_age | consumer_% | lawyer_% |
|---|---|---|---|---|---|---|
| OXYCODONE HYDROCHLORIDE | 14,189 | 97.8 | 42.5 | 44.0 | 67.5 | 28.5 |
| RANITIDINE HYDROCHLORIDE | 13,264 | 96.0 | 2.9 | 62.0 | 7.8 | 91.7 |
| LENALIDOMIDE | 11,288 | 39.0 | 7.5 | 71.0 | 3.6 | 0.0 |
| ADALIMUMAB | 8,054 | 88.2 | 5.7 | 57.0 | 70.7 | 0.0 |
| TOFACITINIB CITRATE | 7,514 | 38.5 | 2.9 | 62.0 | 65.0 | 0.0 |
| DUPILUMAB | 7,371 | 13.0 | 0.4 | 58.5 | 85.6 | 0.0 |
| SECUKINUMAB | 6,908 | 35.9 | 1.9 | 54.0 | 68.7 | 0.0 |
| APIXABAN | 5,796 | 87.4 | 19.9 | 78.0 | 76.7 | 0.0 |
| TENOFOVIR DISOPROXIL FUMARATE | 5,406 | 98.4 | 1.4 | 50.0 | 44.4 | 54.2 |
| RITUXIMAB | 5,091 | 99.1 | 6.9 | 60.0 | 11.9 | 0.0 |

- **Most-reported reaction terms** (excluding non-specific terms such as 'Drug ineffective' / 'Off label use')

| reaction | reports |
|---|---|
| Fatigue | 19,170 |
| Pain | 17,435 |
| Nausea | 16,841 |
| Diarrhoea | 16,051 |
| Headache | 13,991 |
| Dyspnoea | 12,752 |
| Arthralgia | 10,524 |
| Dizziness | 9,711 |
| Vomiting | 9,693 |
| Rash | 9,531 |

- **Possible stimulated reporting.** These drugs have a large share of reports from lawyers, a pattern often linked to litigation. Their report counts and PRRs may overstate real-world frequency.

| drug | reports | lawyer_% | consumer_% |
|---|---|---|---|
| RANITIDINE HYDROCHLORIDE | 13,264 | 91.7 | 7.8 |
| TENOFOVIR DISOPROXIL FUMARATE | 5,406 | 54.2 | 44.4 |
| EMTRICITABINE / TENOFOVIR DISOPROXIL FUMARATE | 2,357 | 49.3 | 46.1 |
| DOCETAXEL | 1,235 | 59.0 | 4.7 |
| EFAVIRENZ / EMTRICITABINE / TENOFOVIR DISOPROXIL FUMARATE | 1,213 | 50.2 | 48.8 |
| ACETAMINOPHEN / HYDROCODONE BITARTRATE | 1,111 | 40.8 | 55.7 |
| HYDROMORPHONE HYDROCHLORIDE | 1,004 | 33.0 | 61.2 |
| ACETAMINOPHEN / OXYCODONE HYDROCHLORIDE | 582 | 49.3 | 47.4 |

## 3. Drug-reaction pairs flagged for review

Of **86,903** drug-reaction pairs with at least 3 reports, **44,899** meet the Evans screening criteria (n>=3, PRR>=2, chi-square>=4) after removing non-specific terms. Two views follow.

**a) Largest strong signals** - at least 50 reports, PRR>=5, 95% ROR lower bound above 1, ranked by number of reports:

| drug | reaction | reports | PRR | ROR_lower_95 | fatal_% |
|---|---|---|---|---|---|
| TENOFOVIR DISOPROXIL FUMARATE | Renal injury | 3,714 | 504.1 | 1,456.5 | 1.2 |
| TENOFOVIR DISOPROXIL FUMARATE | Skeletal injury | 3,153 | 1,225.5 | 2,536.8 | 1.6 |
| TENOFOVIR DISOPROXIL FUMARATE | Bone density decreased | 3,016 | 91.3 | 192.1 | 0.6 |
| RANITIDINE HYDROCHLORIDE | Colorectal cancer | 2,599 | 465.5 | 496.6 | 1.2 |
| TENOFOVIR DISOPROXIL FUMARATE | Osteonecrosis | 2,230 | 164.2 | 257.2 | 0.3 |
| TENOFOVIR DISOPROXIL FUMARATE | Bone loss | 2,142 | 176.5 | 268.3 | 0.3 |
| TENOFOVIR DISOPROXIL FUMARATE | Chronic kidney disease | 1,936 | 41.5 | 60.1 | 1.1 |
| TENOFOVIR DISOPROXIL FUMARATE | Renal failure | 1,820 | 42.1 | 59.0 | 2.0 |
| RANITIDINE HYDROCHLORIDE | Renal cancer | 1,714 | 274.6 | 271.9 | 1.2 |
| TENOFOVIR DISOPROXIL FUMARATE | Multiple fractures | 1,647 | 194.1 | 253.5 | 0.5 |
| RANITIDINE HYDROCHLORIDE | Bladder cancer | 1,525 | 170.0 | 169.0 | 1.9 |
| EMTRICITABINE / TENOFOVIR DISOPROXIL FUMARATE | Bone density decreased | 1,463 | 64.3 | 153.7 | 0.9 |

**b) Most disproportionate pairs** - at least 20 reports, ranked by PRR (rare drug + rare reaction pairs rise to the top, so this view surfaces unusual and often highly specific effects):

| drug | reaction | reports | PRR | ROR_lower_95 | fatal_% |
|---|---|---|---|---|---|
| OLANZAPINE PAMOATE | Post-injection delirium sedation syndrome | 26 | 111,160.5 | 51,070.5 | 0.0 |
| ETELCALCETIDE HYDROCHLORIDE | Shunt stenosis | 35 | 94,193.2 | 16,335.7 | 2.9 |
| COLLAGENASE CLOSTRIDIUM HISTOLYTICUM | Penile contusion | 116 | 91,870.3 | 16,225.3 | 0.0 |
| ETONOGESTREL | Pregnancy with implant contraceptive | 92 | 74,663.5 | 5,066.6 | 0.0 |
| COLLAGENASE CLOSTRIDIUM HISTOLYTICUM | Penile haematoma | 33 | 52,966.8 | 3,450.8 | 0.0 |
| INOTERSEN SODIUM | Urine protein/creatinine ratio abnormal | 23 | 47,072.1 | 7,090.4 | 0.0 |
| COLLAGENASE CLOSTRIDIUM HISTOLYTICUM | Genital contusion | 23 | 37,155.8 | 2,354.2 | 0.0 |
| NITISINONE | Lenticular opacities | 34 | 34,723.1 | 31,999.5 | 0.0 |
| DABIGATRAN ETEXILATE MESYLATE | Procoagulant therapy | 27 | 32,715.4 | 2,071.4 | 0.0 |
| COPPER | Foreign body in reproductive tract | 441 | 28,581.3 | 8,205.9 | 0.0 |
| BEVACIZUMAB | Ciliary hyperaemia | 23 | 27,995.1 | 1,755.1 | 0.0 |
| INOTERSEN SODIUM | Urine protein/creatinine ratio increased | 65 | 26,606.0 | 15,201.8 | 0.0 |

**c) Pairs where at least half of the reports are fatal** (n>=20, terms that are fatal by definition such as 'Completed suicide' removed):

| drug | reaction | reports | PRR | fatal_% |
|---|---|---|---|---|
| RIVAROXABAN | Acute kidney injury | 189 | 3.5 | 51.9 |
| SACUBITRIL / VALSARTAN | Myocardial infarction | 128 | 6.1 | 50.8 |
| RIVAROXABAN | Cerebral haemorrhage | 102 | 15.9 | 54.9 |
| OXYCODONE HYDROCHLORIDE | Cardiac arrest | 88 | 2.1 | 61.4 |
| TISAGENLECLEUCEL | Cytopenia | 86 | 307.3 | 55.8 |
| TISAGENLECLEUCEL | Hypoxia | 71 | 82.6 | 59.2 |
| CARBIDOPA / LEVODOPA | Pneumonia | 71 | 2.5 | 50.7 |
| PIMAVANSERIN TARTRATE | Parkinson's disease | 68 | 37.8 | 76.5 |
| TISAGENLECLEUCEL | Thrombocytopenia | 67 | 27.3 | 55.2 |
| RIVAROXABAN | Haemorrhagic stroke | 66 | 61.3 | 68.2 |

_How to read it:_ a high PRR means the reaction is reported far more often for this drug than for other drugs. Check each pair against the product label and literature before concluding anything - known, expected effects (for example an injection-site reaction for an injectable) will also score highly.

## 4. Unusual reporting trends

Weekly report counts were compared with each drug's own typical week (robust z-score >= 3.5, at least 10 reports in the week).

| drug | week | reports | typical_week | times_typical |
|---|---|---|---|---|
| ADAPALENE | 2020-10-19 | 1,223 | 1.0 | 1,223.0 |
| COPPER | 2020-12-28 | 2,243 | 11.0 | 203.9 |
| ADAPALENE | 2020-10-26 | 873 | 1.0 | 873.0 |
| ADAPALENE | 2020-12-21 | 868 | 1.0 | 868.0 |
| ADAPALENE | 2020-11-09 | 795 | 1.0 | 795.0 |
| ADAPALENE | 2020-12-14 | 696 | 1.0 | 696.0 |
| CARIPRAZINE | 2020-10-19 | 678 | 2.0 | 339.0 |
| COLLAGENASE CLOSTRIDIUM HISTOLYTICUM | 2020-12-14 | 501 | 2.0 | 250.5 |
| LINACLOTIDE | 2020-10-05 | 959 | 4.0 | 239.8 |
| COPPER | 2020-12-21 | 969 | 11.0 | 88.1 |

Sudden spikes often come from **batch submissions** (a manufacturer or law firm filing many old cases at once), so check the submission source before treating a spike as new safety information.

## 5. Data quality

Largest issues (high / medium severity):

| category | check | affected | total | pct_% | severity |
|---|---|---|---|---|---|
| Missing values | Event date missing | 217,138 | 436,148 | 49.8 | medium |
| Missing values | Age missing | 206,151 | 436,148 | 47.3 | medium |
| Inconsistent records | Therapy started after the event (suspect drugs) | 43,503 | 189,254 | 23.0 | medium |
| Duplicates | Possible duplicate reports (same event date, age, sex, country, drug) | 14,814 | 436,148 | 3.4 | medium |
| Inconsistent records | Age group code disagrees with age | 142 | 436,148 | 0.0 | medium |
| Inconsistent records | Weight implausible (<0.3 kg or >400 kg) | 51 | 436,148 | 0.0 | medium |
| Inconsistent records | Age out of range (<0 or >120 y) | 4 | 436,148 | 0.0 | high |
| Inconsistent records | Event date before 1950 | 2 | 436,148 | 0.0 | medium |
| Inconsistent records | Event date after FDA receipt date | 0 | 436,148 | 0.0 | high |
| Inconsistent records | Age present but unit missing | 0 | 436,148 | 0.0 | medium |

Handling rules: only the latest version of each case is kept; ages converted to years and set to missing when outside 0-120; weights converted to kg and checked; drug names standardised to active ingredient; duplicate reaction terms removed; placeholders such as 'UNKNOWN' excluded from drug-level analysis.

## 6. Records and trends flagged for human review

| flag_type | severity | cases |
|---|---|---|
| POSSIBLE_DUPLICATE | medium | 14,814 |
| FATAL_CASE_WITH_SIGNAL | high | 2,603 |
| AGE_GROUP_MISMATCH | medium | 142 |
| WEIGHT_IMPLAUSIBLE | medium | 51 |
| NO_PRIMARY_SUSPECT | medium | 6 |
| AGE_IMPLAUSIBLE | high | 4 |

Priority order suggested: (1) fatal cases that contain a strong signal, (2) records with impossible values, (3) possible duplicates, (4) records missing a reaction or suspect drug.

## 7. Limitations

- Reports are voluntary and incomplete; the real number of patients exposed is unknown, so rates cannot be calculated.
- A report does not prove the drug caused the event; underlying disease, other medicines and coincidence are common explanations.
- Reporting is affected by publicity, litigation, drug age and regulatory requirements (stimulated reporting).
- Age, sex, dates and outcomes are often missing, so some charts describe only a subset of cases.
- Possible-duplicate detection is rule-based and will miss some duplicates and over-flag some separate patients.
- One quarter of data limits trend analysis; load more quarters for longer trends.

## 8. Suggested next steps

1. Medical reviewers assess the top flagged pairs against label, literature and clinical plausibility.
2. Request follow-up information (dates, dose, concomitant drugs, dechallenge/rechallenge) for fatal flagged cases.
3. Confirm trend spikes with the company's own safety database and check for news, recalls or litigation notices.
4. Fix upstream data-capture issues behind the largest data-quality gaps.
5. Add more quarters and re-run to see whether signals persist.
