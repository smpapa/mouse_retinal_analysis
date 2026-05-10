# OCT HITL Editor 사용 설명서

마우스 OCT B-scan boundary 자동 검출 결과를 사용자가 검토·보정하는 데스크톱 도구.

---

## 1. 설치 및 실행

### 패키지 받기
`OctHitlEditor_full.zip` (~300 MB) 한 파일을 임의의 폴더에 압축 해제. 예:
```
C:\OctTool\OctHitlEditor_full\
├── OctHitlEditor.exe        ← 더블클릭
├── _internal\               ← Qt + Python 런타임 (건드리지 말 것)
└── data\                    ← OCT 이미지 + DB
```

### 실행
`OctHitlEditor.exe` 더블클릭 → 5–30초 후 메인 창 표시.

### 시스템 요구사항
- **Windows 10/11 (64-bit)**
- 디스크 600 MB 이상 (DB가 커지면 더 필요)
- Visual C++ Redistributable 14.x (대부분 자동 설치되어 있음. 없으면 [Microsoft 공식](https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist)에서 다운로드)
- 파이썬·라이브러리 사전 설치 **불필요**

---

## 2. 화면 구성

```
┌─ OCT HITL Editor ─────────────────────────────────────────┐
│ File   Tools                                              │ ← 메뉴바
├──────────────────┬────────────────────────────────────────┤
│ Drag Erase Undo Save                                      │ ← 툴바
├──────────────────┴────────────────────────────────────────┤
│ 📁 Files (96)    │                                        │
│ ✓ 21_OS_4H       │                                        │
│   21_OS_4H(1)    │      [B-scan + boundary lines]         │ ← 캔버스
│ ✓ 21_OS_6H       │                                        │
│ ◉ 21_OS_8H       │                                        │
│ ...              │                                        │
│                  │                                        │
│ Boundaries:      │                                        │
│ ☑ TOP            │                                        │
│ ☑ ONL            │                                        │
│ ☑ BM             │                                        │
│ ☑ DET top        │                                        │
│ ☑ DET bottom     │                                        │
├──────────────────┴────────────────────────────────────────┤
│ 21_OS_8H.tif | 1535 cols | edited: TOP, BM | ●  │ x=512 ...│ ← 상태바
└────────────────────────────────────────────────────────────┘
```

| 영역 | 역할 |
|---|---|
| 사이드바 (좌측 상단) | 파일 목록. ✓ = 보정 완료 |
| Boundaries 체크박스 (좌측 하단) | 5개 boundary 표시/숨김 |
| 캔버스 (중앙) | OCT 이미지 + boundary 라인 + 편집 영역 |
| 상태바 (좌측) | 파일명, 컬럼 수, 편집 상태, dirty 마커 (●) |
| 상태바 (우측) | 호버 위치의 측정값 (실시간) |

### Boundary 색상

| 색 | 의미 |
|---|---|
| 🔴 빨강 | TOP (망막 상단) |
| 🟢 초록 | ONL (외핵층 경계) |
| 🔵 파랑 | BM (Bruch 막, 망막 하단) |
| 🟡 노랑 | DET top (detachment 상단) |
| 🟣 마젠타 | DET bot (detachment 하단) |

패널 좌우 빨간 수직선 = B-scan 패널 시작/끝
패널 중앙 노란 점선 = 패널 중심

---

## 3. 기본 작업 흐름

### A. 자동 분석된 결과 보기 (이미 되어 있음)
1. 사이드바에서 파일 클릭 → 캔버스에 표시
2. 상태바에 파일명, 컬럼 수 확인
3. 캔버스 위 마우스 이동 → 우측 상태바에 그 컬럼의 측정값 실시간 표시
   ```
   x=512 | TOP=82 ONL=110 BM=148 | total=255.4μm outer=146.7μm
   ```

### B. Boundary 보정 (Drag 모드)
1. 툴바 `Drag` 활성화 (기본값) — 또는 `D` 키
2. 키 `1`–`5`로 편집할 boundary 선택 (1=TOP, 2=ONL, 3=BM, 4=DET top, 5=DET bot)
3. 마우스로 **클릭 + 드래그** — boundary가 마우스 경로를 따라 그대로 그려짐
4. 마우스 이동 중 새 위치가 잘못 그려졌으면 즉시 다시 드래그

### C. Boundary 지우기 (Erase 모드)
잘못 검출된 영역에서 boundary를 명시적으로 비울 때 사용.
1. 툴바 `Erase` 클릭 — 또는 `E` 키
2. 마우스 드래그 → 빨간 반투명 박스로 지울 x 범위 표시
3. 손 떼면 그 범위의 boundary가 NaN으로 비워짐
4. 측정 시 해당 컬럼은 제외됨

### D. 되돌리기 / 저장
- **`Ctrl+Z`**: 마지막 편집 되돌리기 (50단계)
- **`Ctrl+S`**: DB에 저장 — 즉시 (~5ms)
  - 사이드바에 ✓ 표시
  - 상태바에 "Saved 21_OS_8H.tif"
  - dirty 마커 ● 사라짐
- 저장은 **로컬 DB**(`output\db\oct_results.db`)에 들어감. xlsx는 별도 export 단계.

### E. 다른 이미지로 이동
- 사이드바 클릭 / **←** / **→** 키
- dirty 상태(미저장 편집 있음)에서 이동 시 → "Save changes? Save / Discard / Cancel" 다이얼로그

---

## 4. 메뉴 상세

### File
| 항목 | 단축키 | 동작 |
|---|---|---|
| **Open Data Folder...** | `Ctrl+O` | 다른 데이터 폴더 선택. `output/db/` 없으면 자동 분석 실행 여부 확인 |
| **Save** | `Ctrl+S` | 현재 이미지를 DB에 저장 |
| **Export to Excel...** | — | DB 전체를 xlsx로 export. 진행 다이얼로그 표시 |

### Tools
| 항목 | 동작 |
|---|---|
| **Run Auto Analysis...** | 현재 폴더의 TIFF에 대해 알고리즘 재실행. 진행률 표시. 완료 시 DB의 자동값(auto_*) 갱신, 사용자 보정값(corr_*)은 유지 |
| **Export Annotations (CSV + TIFF)...** | 보정한 이미지(✓)만 골라 학습용 CSV + 시각화 TIFF로 export |
| **Convert Legacy Annotation TIFFs to HITL Colours...** | 기존 Heidelberg 색상 annotation TIFF (4H/6H 등)를 HITL 색상으로 일괄 변환 |

---

## 5. 키보드 단축키 모음

| 키 | 동작 |
|---|---|
| `1` ~ `5` | active boundary 전환 (TOP / ONL / BM / DET top / DET bot) |
| `D` / `E` | Drag / Erase 모드 전환 |
| `←` / `→` | 이전 / 다음 이미지 |
| `Ctrl+Z` | Undo (마지막 편집 되돌리기) |
| `Ctrl+S` | Save (DB에 저장) |
| `Ctrl+O` | Open Data Folder |
| `Ctrl + 마우스 휠` | 캔버스 줌 인/아웃 |
| **마우스 우클릭 + 드래그** | 캔버스 pan (이동) |

---

## 6. 데이터 폴더 구조

`File > Open Data Folder`로 선택한 폴더는 다음 형태로 구성됨:

```
data\mouse_data_org\
├── 21_OS_4H.tif                    ← 원본 OCT TIFF (96장)
├── 21_OS_4H(1).tif
├── ...
└── output\
    ├── db\
    │   └── oct_results.db          ← 보정값 저장소 (canonical)
    ├── oct_results.xlsx            ← Export 결과 (자동 검출 + 보정 컬럼)
    ├── 21_OS_4H_overlay.png        ← 자동 분석 시각화
    ├── 21_OS_4H_overlay_corrected.png  ← 보정 시각화
    └── annotations\
        ├── csv\
        │   └── 21_OS_4H.csv        ← 학습용 per-column 데이터
        └── tiff\
            └── 21_OS_4H_annotation_hitl.tiff  ← HITL 색상 GT 이미지
```

**핵심**: `output\db\oct_results.db` 1개 파일만 백업하면 모든 보정값 보존.

### 새 데이터 폴더로 시작하기
1. 새 폴더에 TIFF 파일들 복사 (예: `D:\new_oct\img1.tif, img2.tif, ...`)
2. `File > Open Data Folder...` → 그 폴더 선택
3. `output\` 폴더 없으면 → "자동 분석 실행하시겠습니까?" 다이얼로그 → **Yes**
4. 분석 후 사이드바에 파일 목록 자동 채워짐 → 편집 시작

---

## 7. 측정값 해석

### 두께 (μm 단위)
| 측정값 | 정의 |
|---|---|
| `total` | (BM y) − (TOP y) × scale = 망막 전체 두께 |
| `outer` | (BM y) − (ONL y) × scale = 외망막 두께 |
| `det` | (DET bot y) − (DET top y) × scale = detachment 두께 |

scale = `3.87 µm/px` (이 데이터셋의 Heidelberg 마우스 OCT 기준)

### 자동값 vs 보정값
xlsx 시트에서:
- `TOP_y`, `ONL_y` 등 = **자동 검출값** (불변)
- `TOP_y_corrected` 등 = **사용자 보정값** (있으면 이게 최종)
- `total_thickness_um` = 자동 두께
- `total_thickness_um_corrected` = 보정 반영 두께 (최종 측정)

분석 시 항상 `*_corrected` 컬럼이 비어있지 않으면 그 값을, 비어있으면 `*` 컬럼 값을 사용.

`corrected_summary` 시트에 이미지별 `mean_total_um` (자동) vs `mean_total_um_corrected` (보정 후) 비교 표시.

---

## 8. 자주 쓰는 시나리오

### 시나리오 1: 한 이미지 빠르게 보정 후 저장
```
1. 사이드바에서 21_OS_8H 클릭
2. `2` 키 → ONL 활성화
3. 잘못 검출된 영역 위에서 클릭 + 드래그
4. Ctrl+S → 저장 (즉시)
5. → 키 → 다음 이미지
```

### 시나리오 2: detachment 영역 바깥의 잘못된 DET 라인 지우기
```
1. `4` 키 → DET top 활성화
2. `E` 키 → Erase 모드
3. 클릭 + 드래그로 지울 x 범위 선택
4. 손 떼면 그 영역의 DET top = NaN
5. `5` 키 → DET bot
6. 같은 영역 erase
7. Ctrl+S
```

### 시나리오 3: 보정 결과를 분석 도구로 export
```
1. File > Export to Excel... → 진행 다이얼로그 → 완료
2. output\oct_results.xlsx에 *_corrected 컬럼 + corrected_summary 시트 갱신
3. 외부 분석 도구(Excel/pandas/R 등)에서 읽어서 사용
```

### 시나리오 4: 학습용 데이터 export
```
1. Tools > Export Annotations (CSV + TIFF)...
2. 출력 폴더 선택 (기본: output\annotations)
3. 보정한 이미지(✓)만 골라 CSV + TIFF 생성
4. CSV: ML boundary regression 학습용
5. TIFF: ML segmentation 또는 시각화용
```

### 시나리오 5: 알고리즘 재실행 (보정값 보존)
```
알고리즘 코드/파라미터를 변경한 경우:
1. Tools > Run Auto Analysis... → 진행 다이얼로그
2. 완료 후 DB의 auto_* 컬럼 갱신, corr_* 컬럼 그대로 보존
3. 사이드바 ✓ 마커도 그대로 유지
4. 자동 검출이 좋아진 이미지는 더 이상 보정 불필요
```

---

## 9. 트러블슈팅

### exe 실행 시 즉시 종료
같은 폴더에 `_internal\` 디렉터리가 있는지 확인. zip 압축 해제가 부분적으로 됐을 수 있음.

### "DLL load failed" 오류
Visual C++ Redistributable 14.x 미설치. Microsoft 공식 사이트에서 받아 설치.

### 첫 실행이 매우 느림 (10초+)
정상. Windows Defender의 첫 스캔 + DLL 로드. 두 번째 실행부터 빠름.

### Save 시 "Could not write..." 오류
xlsx export 중 오류. 가장 흔한 원인:
- Excel에서 `oct_results.xlsx` 파일을 열어둠 → Excel 닫고 재시도
- 디스크 권한 문제 → 다른 폴더로 데이터 이동

### Boundary 라인이 IR fundus 영역에 그려짐
정상이 아님. 알려주시면 수정. (현재 검출기는 96장 모두 정확히 panel 시작점 검출 확인됨.)

### dirty 마커(●)가 안 사라짐
`Ctrl+S` 누르면 사라져야 함. 만약 남아있으면 저장이 실패한 것 — 상태바 메시지 확인.

### 종료 시 dialog가 나타남
"Unsaved changes" + "DB 저장 후 xlsx 자동 export" 진행. xlsx export는 ~10초 소요. 편집한 적 없으면 즉시 종료.

---

## 10. 데이터 백업

가장 중요한 파일 단 하나:
```
data\mouse_data_org\output\db\oct_results.db
```
이 파일만 복사해두면 모든 보정값 백업 완료. 다른 PC에 복원할 때:
1. exe + `data\mouse_data_org\` 폴더 구조 그대로 준비
2. `output\db\oct_results.db`만 백업본으로 교체
3. 실행 → 사이드바 ✓ 마커, 모든 보정값 그대로

---

## 11. 추가 정보

- 소스 저장소: https://github.com/smpapa/mouse_retinal_analysis
- 시스템 동작 원리 상세: 저장소의 `docs/hitl_flow.md`
- 빌드 방법 (개발자용): 저장소의 `docs/build_standalone.md`

문제 신고 / 기능 요청은 GitHub Issues 또는 직접 연락.
