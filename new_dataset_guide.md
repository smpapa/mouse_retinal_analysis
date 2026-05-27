# 새 OCT 데이터셋 사용 가이드

기존 데이터를 다른 OCT 이미지 세트로 교체하거나, 새 이미지를 추가하는 3가지 방법.

---

## 시나리오 A — 새 데이터셋을 별도 폴더에서 시작 ⭐ (권장)

기존 데이터(`data\mouse_data_org\`)는 그대로 두고 새 폴더에서 완전 독립적으로 시작.

### 절차

1. 새 폴더 생성 (위치 자유): `D:\new_oct_2026\`
2. 새 TIFF 파일들 복사
3. `OctHitlEditor.exe` 실행
4. `File > Open Data Folder...` → `D:\new_oct_2026\` 선택
5. "No analysis found. Run auto analysis now?" → **Yes**
6. 진행 다이얼로그 (1–3분, 이미지 수 비례)
7. 사이드바에 새 파일들 채워짐 → 편집 시작

### 자동 생성되는 폴더 구조

```
D:\new_oct_2026\
├── img001.tif
├── img002.tif
├── ...
└── output\                              ← 자동 생성
    ├── db\oct_results.db                ← 새 데이터셋 전용 DB
    ├── oct_results.xlsx                 ← 자동 분석 xlsx
    ├── img001_overlay.png               ← 자동 검출 시각화
    └── (이후 편집 시 corrected 컬럼, annotations 폴더 등 추가)
```

### Excel Export 동작

`File > Export to Excel...` 누르면 그 폴더의 `output\oct_results.xlsx`에 저장:
- 기존 데이터셋 xlsx 영향 없음
- 새 데이터셋만의 독립적인 결과
- 형식 동일 (자동값 컬럼 + `*_corrected` 컬럼 + `corrected_summary` 시트)

### 데이터셋 간 전환

`File > Open Data Folder...`로 언제든 왔다 갔다 가능:
- 새 폴더 ↔ 기존 폴더
- 각 폴더의 DB가 독립적이라 보정값 섞일 일 없음
- 사이드바, ✓ 마커, 캔버스 모두 자동 갱신

### 두 데이터셋을 같이 분석

pandas 등으로 각 xlsx 따로 읽어서 비교:

```python
import pandas as pd
df_old = pd.read_excel(r"data\mouse_data_org\output\oct_results.xlsx", sheet_name="summary")
df_new = pd.read_excel(r"D:\new_oct_2026\output\oct_results.xlsx", sheet_name="summary")
```

### 장점 / 단점

| 장점 | 단점 |
|---|---|
| 기존 데이터 완전 보호 | 매번 폴더 전환 필요 |
| 여러 데이터셋 동시 관리 | — |
| exe 업데이트 시 데이터 영향 없음 | — |

---

## 시나리오 B — 기존 폴더의 TIFF를 새 이미지로 완전 교체

기존 폴더(`data\mouse_data_org\`) 위치를 유지하면서 안의 TIFF만 새것으로.

> ⚠️ **기존 보정값 손실** — 반드시 DB 백업 후 진행.

### 절차

```cmd
:: 1. 기존 DB 백업
copy data\mouse_data_org\output\db\oct_results.db ^
     C:\backup\oct_results_2026-05-28.db

:: 2. 기존 output 폴더 통째 삭제 (DB + xlsx + overlay 등)
rmdir /S /Q data\mouse_data_org\output

:: 3. 기존 TIFF 삭제 (또는 다른 폴더로 이동)
del data\mouse_data_org\*.tif

:: 4. 새 TIFF 복사
copy D:\source\new_*.tif data\mouse_data_org\
```

5. `OctHitlEditor.exe` 실행 → 자동으로 `data\mouse_data_org\` 인식
6. "Run auto analysis now?" → **Yes**
7. 새 분석 결과로 출발

### 복구 (백업한 DB로 되돌리기)

```cmd
copy /Y C:\backup\oct_results_2026-05-28.db ^
        data\mouse_data_org\output\db\oct_results.db
```
+ 옛 TIFF도 다시 복사. DB와 TIFF가 일치해야 정상 동작.

### 언제 이 시나리오?

- 한 폴더에서 데이터셋을 순차적으로 처리 (한 번에 하나만 보존)
- 디스크 공간 절약 (기존 데이터 정리 필요할 때)
- 외부 시스템이 항상 `data\mouse_data_org\` 경로를 참조하는 경우

대부분의 경우 **시나리오 A가 더 안전**.

---

## 시나리오 C — 기존 데이터셋에 새 이미지 추가 (보정값 유지)

기존 96장의 보정값 그대로 두고 새 이미지만 추가.

### 절차

1. 새 TIFF들을 `data\mouse_data_org\`에 그냥 복사 (기존 파일 건드리지 말 것)
   ```cmd
   copy D:\source\new_*.tif data\mouse_data_org\
   ```
2. `OctHitlEditor.exe` 실행 (기존 DB + 보정값 그대로 로드)
3. `Tools > Run Auto Analysis...` 클릭
4. batch_process가 폴더의 전체 TIFF (기존 96장 + 새 이미지)에 알고리즘 실행
5. 완료 후 DB에 새 이미지 자동값 추가, 기존 96장의 보정값(`corr_*`) **완전 보존**
6. 사이드바에 새 이미지 추가됨, 기존 ✓ 마커 그대로

### 작동 원리

`db.import_from_xlsx(preserve_corrected_in_db=True)`:
- 기존 stem: 보정값 그대로 유지, 자동값만 갱신
- 새 stem: 자동값만 추가 (보정값은 NaN 초기 상태)

### 언제 이 시나리오?

- 같은 디바이스로 같은 종류의 OCT를 시간 차이로 받는 경우
- 통합 분석이 필요 (한 xlsx, 한 DB에서 처리)
- 추가된 이미지만 보정하면 됨

### 주의

새 이미지가 다른 디바이스/해상도라면 `scale_um_per_px_y`가 다를 수 있음 — 절대 두께 값에 일률 오차. 같은 디바이스끼리만 권장.

---

## 시나리오 선택 가이드

| 상황 | 권장 |
|---|---|
| 완전히 새 프로젝트 / 다른 실험 데이터 | **A** |
| 기존 데이터 폐기 + 같은 폴더에서 시작 | **B** |
| 같은 실험에 이미지 추가 (보정값 유지) | **C** |
| 여러 데이터셋 비교 분석 필요 | **A** (폴더별 분리) |

---

## 폴더 위치 권장

| 데이터 위치 | 장점 | 단점 |
|---|---|---|
| 패키지 내부 (`OctHitlEditor_full\data\`) | 단일 폴더로 배포 쉬움 | 다른 PC로 이동 시 데이터 함께 따라감, exe 업데이트 시 데이터 영향 |
| **별도 폴더 (`D:\research\my_oct\`)** ⭐ | 데이터/도구 분리, 여러 데이터셋 관리 쉬움 | 매번 `File > Open Data Folder`로 선택 필요 |

**추천**: 분석할 OCT 데이터는 별도 폴더에 두고, exe 패키지는 도구로만 사용. exe 업데이트해도 데이터 안전.

---

## 자주 묻는 질문

**Q: 새 폴더 첫 분석이 너무 오래 걸려요**
A: 이미지 수에 비례 (96장 ≈ 1–3분). 한 번만 하면 다음 실행부터는 즉시 로드 (DB가 캐시 역할).

**Q: 같은 폴더로 `Open Data Folder`를 두 번 하면?**
A: DB 이미 있으면 즉시 로드 (재분석 안 함). 빠름. 보정값 그대로.

**Q: 이미지 파일명 규칙은?**
A: 자유. 단 `*_annotation.tiff` 같은 패턴은 피해주세요 (GT 어노테이션 파일로 오인). 예: `mouse01_oct.tif`, `sample_A_20260101.tiff` 등 OK.

**Q: 새 이미지가 다른 디바이스(해상도)에서 나왔으면?**
A: `scale_um_per_px_y`가 다를 수 있음. 현재 fallback `3.87 μm/px`이 일률 적용. 디바이스 섞인 데이터는 절대 두께값 비교 시 주의.

**Q: 종료 시 자동 export는 어느 데이터셋으로?**
A: 가장 마지막에 열려 있던 데이터셋의 `output\oct_results.xlsx`. 두 데이터셋을 번갈아 작업했다면 마지막 폴더만 자동 export됨. 각 데이터셋에서 명시적으로 `File > Export to Excel...` 권장.

**Q: 모든 데이터셋을 한 번에 export?**
A: 현재 메뉴에 없음. 각 데이터셋을 따로 열어서 한 번씩 export 필요. (자주 쓸 거면 batch export 메뉴 추가 가능 — 요청 시 구현.)

**Q: 기존 데이터셋과 새 데이터셋을 합치고 싶다면?**
A: 자동으론 안 됨. 두 가지 방법:
1. pandas로 두 xlsx 시트 합치기 (분석용)
2. 두 폴더의 TIFF를 한 폴더로 합치고 단일 데이터셋으로 재분석 (시나리오 B/C)

---

## 빠른 참조 카드

```
새 프로젝트 시작 → 시나리오 A → File > Open Data Folder
                                  → 새 폴더 → Yes (auto analysis)

기존 폴더 새로고침 → 시나리오 B → DB 백업 → 폴더 비움 → 새 TIFF →
                                  exe → Yes (auto analysis)

이미지 추가 (보정 유지) → 시나리오 C → 새 TIFF 복사 → exe →
                                       Tools > Run Auto Analysis
```
