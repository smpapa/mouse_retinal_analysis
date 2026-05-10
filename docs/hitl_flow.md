# HITL 시스템 동작 플로우

> OCT 자동 boundary 분석 결과를 사람이 검토·보정하는 PySide6 데스크톱 에디터의 전체 흐름.
> Source: `src/hitl/`. Design 문서: [`plans/2026-05-09-hitl-design.md`](plans/2026-05-09-hitl-design.md).

## 한 줄 요약

`batch_process.py`가 96장의 OCT TIFF를 분석해 `oct_results.xlsx`와 자동 overlay PNG를 만들고, HITL 에디터(`python -m src.hitl.main`)는 그 xlsx를 한 번 SQLite DB(`output/db/oct_results.db`)로 import한 뒤 모든 편집을 DB에 저장한다(~5ms). 종료 시 또는 `File > Export to Excel`을 누르면 DB에서 xlsx를 다시 만들어낸다. xlsx 형식은 기존(`*_corrected` 컬럼 + `corrected_summary` 시트)과 동일.

---

## 단계 1 — 자동 분석

두 가지 방법:

**(a) CLI로 사전 실행** — HITL 띄우기 전:

```bash
python -m src.batch_process <data_folder>
```

**(b) HITL 에디터 안에서 실행** — `Tools > Run Auto Analysis`

이 메뉴는 현재 선택된 데이터 폴더 (또는 `File > Open Data Folder`로 막 고른 폴더)에 대해 `batch_process.batch_run`을 백그라운드 워커 스레드(`BatchWorker`)로 실행한다. 진행 상황은 `QProgressDialog`로 표시 (`[i/N] filename.tif`). 완료되면 결과 워크북이 자동으로 다시 로드되어 사이드바에 96개 파일이 채워진다.

처리 내용:

1. `data/mouse_data_org/*.tif` 96개 OCT 이미지 로드
2. 각 이미지마다:
   - `io_utils.load_oct()`: IR fundus 원과 B-scan 패널 영역 자동 검출 (`left_x`, `right_x`, `top_y`, `bot_y`, `center_x`)
   - `oct_analyzer.detect_boundaries()`: B-scan에서 boundary 5개를 컬럼 단위로 검출
     - **TOP** (망막 상단)
     - **ONL** (외핵층 경계)
     - **BM** (Bruch's membrane, 망막 하단)
     - **DET top / DET bottom** (detachment 영역, 없으면 NaN)
   - `viz.save_overlay()`: 원본 + 컬러 boundary line + 패널 시작/중앙/끝 마커가 그려진 PNG 저장
3. 산출물 → `data/mouse_data_org/output/`:
   - `oct_results.xlsx`:
     - `summary` 시트: 96 행, `filename` + 각종 평균 두께 + `scale_um_per_px_y`
     - 이미지별 상세 시트(시트명 28자 truncate): `x_local`, `TOP_y`, `ONL_y`, `BM_y`, `DET_top_y`, `DET_bottom_y`, `total_thickness_um`, `outer_thickness_um`, `detachment_thickness_um`
   - `<basename>_overlay.png` (96개): 원본 + 자동 boundary 시각화

이 시점에서 자동 측정 결과는 완성. HITL은 **이 결과를 수정할 수 있게** 해주는 도구.

---

## 단계 2 — HITL 에디터 실행

```bash
python -m src.hitl.main
# 옵션:
python -m src.hitl.main --workbook <path>.xlsx --image-dir <data_folder>
```

`MainWindow.__init__`:

1. 인자로 받은 `workbook_path`가 존재하면 `storage.load_workbook(oct_results.xlsx)` — 96개 시트를 모두 읽어 메모리에 적재
   - `summary` 시트의 `filename` 컬럼으로 `stem → sheet_name` 매핑 구축 (sheet name이 28자로 truncate되어 있으므로)
   - 각 이미지마다 `ImageRecord(stem, filename, width, auto={5개 boundary 배열}, corrected={5개 보정 배열})`
   - 이미 `*_corrected` 컬럼이 있으면 (이전 세션 작업물) 함께 로드. `"ERASED"` 문자열 셀은 `ERASED_MARKER (-1e9)`로 변환
2. 워크북이 없으면 빈 사이드바로 시작 — `File > Open Data Folder`로 폴더를 골라 로드
3. UI 빌드: 메뉴바 (`File`, `Tools`), 좌측 dock에 파일리스트 + boundary 체크박스, 중앙에 `OverlayCanvas`, 툴바에 Drag/Erase/Undo/Save
4. 사이드바에 96개 파일 표시 (이미 보정된 파일에는 `✓` 표시)

**메뉴 동작**:

| 메뉴 항목 | 동작 |
|---|---|
| `File > Open Data Folder...` | 폴더 선택 → `output/oct_results.xlsx` 있으면 로드, 없으면 자동 분석 실행 여부 묻기. 미저장 변경이 있으면 Save/Discard/Cancel 프롬프트 |
| `File > Save` | `Ctrl+S` 동일. 현재 이미지 저장 |
| `Tools > Run Auto Analysis...` | 현재 폴더에 `batch_process.batch_run`을 백그라운드 워커 스레드로 실행. 진행 상황은 `QProgressDialog`로 표시. 완료 시 워크북 자동 reload |
| `Tools > Export Annotations (CSV + TIFF)...` | ✓ 표시된 (사용자가 보정한) 이미지들만 골라 CSV 표 + HITL-색상 annotation TIFF로 출력. 출력 폴더 선택 다이얼로그 → `<chosen>/csv/<stem>.csv`, `<chosen>/tiff/<stem>_annotation_hitl.tiff`. ML 학습 / `gt_guided.py` 검증용. TIFF의 boundary 색상은 HITL 캔버스의 색상(빨강 TOP / 초록 ONL / 파랑 BM / 노랑 DET top / 마젠타 DET bot)과 동일 |
| `Tools > Convert Legacy Annotation TIFFs to HITL Colours...` | 기존 Heidelberg-색상 annotation TIFF (4H/6H 등)를 HITL 색상으로 일괄 변환. 입력 폴더(`annotation/`) + 원본 TIFF 폴더 + 출력 폴더 선택. 결과 파일명 `<stem>_annotation_hitl.tiff`. 변환 후 `gt_guided.py`가 동일 마스크로 모든 annotation을 처리 가능 |

---

## 단계 3 — 한 이미지 편집 사이클

### (a) 이미지 선택

사이드바 클릭 또는 ←/→ → `MainWindow.select_image(stem)`:

1. 이전 이미지에 미저장 변경이 있으면 Save/Discard/Cancel 다이얼로그 (`_on_sidebar_image_selected`)
2. 원본 TIFF를 `load_oct()`로 읽음
3. 이 이미지의 `BoundaryEditor`를 lazy 생성 (없으면). `auto`는 batch 결과, `corrected`는 빈 NaN 배열 (또는 이전 세션 보정값)
4. 캔버스에:
   - `set_image(rgb)`: 원본 TIFF 픽스맵을 scene `(0, 0)`에 배치
   - `set_panel_geometry(left_x, right_x, top_y, bot_y, center_x)`: B-scan 패널 영역 명시 → boundary clip + 빨간 좌/우 vertical marker + 노란 중앙 dashed marker
   - `set_editor(editor)`: 5개 boundary line을 `effective(name)`로 그림
   - `set_active_boundary("TOP_y")` 기본값

### (b) Boundary 편집

`BoundaryEditor`의 3가지 상태 표현 (per column):

| `corrected[x]` 값 | 의미 | `effective[x]` |
|---|---|---|
| `NaN` | 미수정 | `auto[x]` 사용 |
| 유한 숫자 | 사용자가 그 값으로 override | `corrected[x]` 사용 |
| `ERASED_MARKER (-1e9)` | 사용자가 명시적으로 비움 | `NaN` |

**Drag 모드 (paint-trace)**:

- 마우스 press → `editor.begin_paint(name, x, y)`: 그 컬럼에 즉시 y 기록, undo 스냅샷 1개 push
- 마우스 move → `editor.paint_to(x, y)`: 직전 (x_prev, y_prev)에서 (x, y)까지 직선 보간으로 모든 정수 컬럼에 y 기록
- 마우스 release → `editor.end_paint()`: 세션 종료
- 결과: 마우스 경로가 그대로 boundary가 됨. `dirty` 플래그 = `True`

**Erase 모드**:

- 좌클릭 + 드래그로 사각형 sweep
- release 시 `editor.apply_erase(name, x_start, x_end)`: 그 x 범위의 `corrected[x] = ERASED_MARKER`

**Undo (Ctrl+Z)**:

- `editor.undo()`: 가장 최근 `_Snapshot`을 pop, `corrected` / `_touched` 원복. (paint, erase 각각 1개의 undo entry)

**Boundary 가시성 체크박스**:

- `BoundaryToggleBar` → `canvas.set_boundary_visible(name, False)`: 라인만 숨김 (데이터 그대로)

**상태바**:

- `{filename} | {width} cols | edited: TOP, ONL | ●` (dirty marker)
- 매 편집 종료 시 `edit_finished` 시그널 → `_refresh_status()` 갱신

**키보드 단축키**:

| 키 | 동작 |
|---|---|
| `1` ~ `5` | active boundary 전환 (TOP / ONL / BM / DET top / DET bottom) |
| `D` / `E` | Drag / Erase 모드 전환 |
| `←` / `→` | 이전 / 다음 이미지 |
| `Ctrl+Z` | Undo |
| `Ctrl+S` | Save |

### (c) 저장 (Ctrl+S)

`MainWindow.save_current_image()`:

1. 현재 editor의 `corrected` 딕셔너리를 복사해 `CorrectedSnapshot(stem, corrected, timestamp)` 생성
2. `storage.save_corrections(workbook_path, [snapshot], scale_um_per_px_y)`:
   - `openpyxl.load_workbook()`로 xlsx 열기
   - summary 시트의 `filename` 컬럼으로 stem → sheet name 매핑
   - 해당 시트만 in-place 수정:
     - `<name>_corrected` 컬럼 5개 write — `ERASED_MARKER` → 문자열 `"ERASED"`, `NaN` → 빈 셀, finite → 숫자
     - **Effective 값으로 thickness 재계산** (이게 핵심 — 보정값이 최종 측정):

       ```
       effective[i] = NaN              (corrected[i] = "ERASED")
                    = corrected[i]      (corrected[i] = 유한 숫자)
                    = auto[i]           (corrected[i] = 빈 셀)

       total_thickness_um_corrected[i]      = (eff_BM[i] - eff_TOP[i])      * scale
       outer_thickness_um_corrected[i]      = (eff_BM[i] - eff_ONL[i])      * scale
       detachment_thickness_um_corrected[i] = (eff_DET_bot[i] - eff_DET_top[i]) * scale
       ```

     - `corrected_by_user` boolean 컬럼: 그 행에 어느 보정이라도 있으면 `True`
   - `corrected_summary` 시트 추가/갱신: `filename | n_corrected_cols | corrected_TOP/ONL/BM/DET | mean_total_um | mean_total_um_corrected | edit_timestamp`
   - `.xlsx.tmp`로 atomic write 후 `os.replace` (원본 보호)
3. 사이드바에 `✓` 마커 + `editor.mark_clean()` (`dirty = False`)
4. `overlay_render.render_corrected_overlay()`:
   - editor의 `effective(name)` 5개를 `BoundaryResult`로 묶어 `viz.save_overlay()` 호출
   - `<basename>_overlay_corrected.png` 별도 저장 (자동 overlay는 그대로 유지)
5. PNG 렌더 실패는 non-fatal — 상태바에 표시만 하고 xlsx는 이미 저장됨

### (d) 종료

- 창 닫기 시 dirty editor 있으면 `closeEvent`에서 Save/Discard/Cancel 프롬프트
- Excel이 xlsx를 잡고 있으면 (Windows sharing violation) 사용자 친화 다이얼로그 표시 후 사이드바 ✓ 표시 안 함

---

## 단계 4 — 최종 측정값 도출

xlsx에 저장된 데이터 구조:

| 컬럼 종류 | 의미 |
|---|---|
| `TOP_y`, `ONL_y`, `BM_y`, `DET_top_y`, `DET_bottom_y` | **자동 검출 (불변)** |
| `total_thickness_um`, `outer_thickness_um`, `detachment_thickness_um` | **자동 두께 (불변)** |
| `*_corrected` (5개) | **사용자 수정값** — 빈 셀 = 자동값 사용, 숫자 = 그 값으로 override, `"ERASED"` = 명시적 NaN |
| `*_thickness_um_corrected` (3개) | **수정 반영 두께** — auto 또는 corrected 중 effective 값으로 재계산 |
| `corrected_by_user` | 행 단위 수정 여부 boolean |
| `corrected_summary` 시트 | 이미지별 `mean_total_um` (자동) vs `mean_total_um_corrected` 비교 |

**최종 측정값을 어떻게 쓸 것인가**:

- `*_corrected` 컬럼이 비어 있으면 `*` (자동) 컬럼의 값을 그대로 사용
- 둘이 다르면 `*_corrected` 값이 사용자 보정 후 최종값
- 통계/비교는 `corrected_summary`의 `mean_total_um_corrected` 컬럼 사용

**재실행 안전성**:

- `batch_process.py`를 다시 돌려도 `*_corrected` 컬럼은 유지됨 (자동 컬럼만 갱신)
- HITL을 다시 띄우면 `load_workbook`이 `*_corrected` 컬럼을 읽어와 사용자가 이전 작업을 이어받음

---

## 데이터 흐름 다이어그램

```
batch_process.py
    │
    ├─→ oct_results.xlsx
    │   ├─ summary
    │   └─ <stem> 시트: TOP_y, ONL_y, BM_y, DET_top_y, DET_bottom_y,
    │                   total/outer/detachment_thickness_um
    └─→ <stem>_overlay.png

         ▼ HITL 에디터

MainWindow
  └─ load_workbook ──→ Workbook.images: dict[stem, ImageRecord]
                       └─ ImageRecord: auto={5}, corrected={5}

  사용자 편집 ─→ BoundaryEditor (메모리)
                  - corrected[x] = NaN | 숫자 | ERASED_MARKER
                  - effective(name) = auto[x]   if corrected NaN
                                      corrected if 숫자
                                      NaN       if ERASED

  save (Ctrl+S)
  ├─ save_corrections (openpyxl in-place)
  │   ├─ <stem> 시트에 *_corrected 5개, *_thickness_um_corrected 3개,
  │   │  corrected_by_user 컬럼 추가/갱신
  │   └─ corrected_summary 시트 행 추가/갱신
  └─ render_corrected_overlay
      └─→ <stem>_overlay_corrected.png
```

이 구조의 장점: **자동 결과를 절대 손상시키지 않으면서** 사용자 보정과 자동 측정을 같은 행에서 비교 가능. 보정 안 한 컬럼은 자동값이 그대로 최종값이 됨.

---

## 모듈 구성 요약

| 파일 | 역할 |
|---|---|
| `src/hitl/main.py` | CLI 엔트리. `--workbook`, `--image-dir` 인자 |
| `src/hitl/app.py` | `MainWindow` — 사이드바 + 캔버스 + 툴바 + 상태바 통합 |
| `src/hitl/storage.py` | `load_workbook` / `save_corrections` (openpyxl in-place) |
| `src/hitl/boundary_model.py` | `BoundaryEditor` — auto / corrected 배열, paint / drag / erase / undo, dirty 플래그 |
| `src/hitl/canvas.py` | `OverlayCanvas` — `QGraphicsView`, 이미지 + boundary line 렌더링, 마우스 이벤트 |
| `src/hitl/sidebar.py` | `FileListView` — `QListWidget`, ✓ 표시, 선택 시그널 |
| `src/hitl/boundary_toggle.py` | `BoundaryToggleBar` — 5개 boundary 가시성 체크박스 |
| `src/hitl/overlay_render.py` | 보정 boundary로 `_overlay_corrected.png` 렌더 (`viz.save_overlay` 재사용) |
| `src/hitl/batch_runner.py` | `BatchWorker` — `Tools > Run Auto Analysis`가 사용하는 `QThread` 워커. `batch_process.batch_run`을 GUI 스레드 밖에서 실행하고 진행 상황을 시그널로 보고 |
| `src/hitl/export_annotations.py` | `Tools > Export Annotations`가 사용하는 어노테이션 내보내기. 보정된 이미지를 CSV (학습용 표) + Heidelberg-호환 annotation TIFF (`gt_guided.py` 검증용)로 출력 |
| `tests/hitl/` | 60+ 테스트 (storage / boundary_model / canvas / sidebar / app / overlay_render / db / export_annotations) |
