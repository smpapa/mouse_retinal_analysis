# 개발환경에서 실행 가이드

소스 코드로 직접 실행하기 — 코드 수정, 알고리즘 튜닝, 새 기능 추가 등.

---

## 1. 사전 준비

### 필수
- **Python 3.11.x** (3.11.6 권장 — 다른 버전은 PySide6/openpyxl 호환성 이슈 가능)
  - Windows: [python.org](https://www.python.org/downloads/) 또는 [pyenv-win](https://github.com/pyenv-win/pyenv-win)
  - 설치 시 "Add to PATH" 체크
- **Git** (소스 클론용)

### 권장
- VS Code / PyCharm (IDE)
- Git Bash 또는 PowerShell

---

## 2. 첫 셋업 (1회)

### A. 소스 클론

```cmd
cd D:\workspace
git clone https://github.com/smpapa/mouse_retinal_analysis.git
cd mouse_retinal_analysis
```

또는 ZIP 다운로드 후 압축 해제.

### B. 가상환경 생성 + 의존성 설치

**PowerShell 또는 CMD**:
```cmd
:: 1. venv 생성
python -m venv .venv

:: 2. 활성화 (PowerShell)
.venv\Scripts\Activate.ps1

:: 또는 CMD
.venv\Scripts\activate.bat

:: 3. 의존성 설치
pip install -r requirements.txt
```

**Git Bash**:
```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

설치 시간: ~3분 (PySide6 200MB 다운로드 포함). 결과:
```
Successfully installed PySide6-6.11.0 numpy-2.x pandas-2.x ...
```

### C. 데이터 준비

OCT TIFF 파일들을 `data\mouse_data_org\` 에 두거나, 다른 폴더에 두고 `--image-dir` 옵션으로 지정.

```cmd
data\mouse_data_org\
├── 21_OS_4H.tif
├── ...
└── output\                ← 자동 생성됨 (분석 후)
```

---

## 3. 실행 방법

### A. HITL 에디터 GUI 실행

```cmd
:: 프로젝트 루트에서, venv 활성화된 상태
python -m src.hitl.main
```

기본 경로 사용 시: `data\mouse_data_org\output\oct_results.xlsx` 자동 로드.

#### 옵션
```cmd
:: 다른 데이터 폴더 사용
python -m src.hitl.main --image-dir D:\new_oct_data ^
                       --workbook D:\new_oct_data\output\oct_results.xlsx

:: 데이터 없이 실행 (GUI 띄운 후 File > Open Data Folder로 선택)
python -m src.hitl.main --image-dir nonexistent
```

빈 사이드바로 시작 → `File > Open Data Folder...`로 폴더 선택.

### B. CLI batch 분석 (GUI 없이)

```cmd
python -m src.batch_process data\mouse_data_org
```

옵션:
```cmd
python -m src.batch_process D:\new_oct_data --output D:\new_oct_data\output
```

진행 상황 콘솔 출력:
```
Processing 96 images from D:\workspace\mouse_retinal_analysis\data\mouse_data_org
  [1/96]     21_OS_10H.tif  meas=1535  total= 245.3um
  [2/96] DET 21_OS_10H(1).tif  meas=1500  total= 254.1um
  ...
Wrote D:\workspace\...\output\oct_results.xlsx
```

### C. 단일 이미지 분석 (디버깅용)

```cmd
python -m src.analyze_single data\mouse_data_org\21_OS_4H.tif
```

콘솔에 boundary 통계 + `output\<stem>_overlay.png` 생성.

---

## 4. 테스트 실행

### 전체 테스트
```cmd
python -m pytest tests/hitl -v
```

### 특정 모듈
```cmd
python -m pytest tests/hitl/test_db.py -v
python -m pytest tests/hitl/test_app.py -v
```

### 특정 테스트
```cmd
python -m pytest tests/hitl/test_db.py::test_save_corrections_round_trip -v
```

### 빠른 실행 (병렬, 자세한 출력 X)
```cmd
python -m pytest tests/hitl -q -n auto
```
(병렬은 `pip install pytest-xdist` 후)

### Qt 테스트만 offscreen
```cmd
:: 윈도우 안 띄우고 테스트
set QT_QPA_PLATFORM=offscreen && python -m pytest tests/hitl
```

---

## 5. 개발 워크플로

### 코드 수정 → GUI에서 즉시 확인

1. IDE에서 코드 수정 (예: `src/hitl/canvas.py`)
2. 저장
3. 실행 중인 GUI 종료
4. `python -m src.hitl.main` 다시 실행

**핫 리로드 없음** — Qt 앱이라 매번 재시작 필요.

### 알고리즘 파라미터 튜닝

`src/oct_analyzer.py`의 상수들 수정:
```python
EDGE_FRAC = 0.7          # boundary edge fraction
RETINA_HEIGHT_MAX_PX = 110  # 최대 retina 높이
NEIGHBOUR_DELTA_PX = 20      # 이웃 컬럼 허용 차이
# ... 등
```

수정 후:
```cmd
:: 1. 자동 분석 재실행
python -m src.batch_process data\mouse_data_org

:: 2. GUI에서 결과 검토
python -m src.hitl.main

:: 3. GT 검증 (annotation 폴더 있으면) — summary 시트의 *_median_err_px 컬럼 확인
```

### 새 기능 추가

1. `src/hitl/` 또는 `src/`에 모듈 추가
2. `tests/hitl/`에 테스트 추가 (TDD 권장)
3. `OctHitlEditor.spec`의 `hiddenimports`에 새 모듈 등록 (exe 빌드 영향 시)
4. `docs/hitl_flow.md` 업데이트

---

## 6. exe 빌드 (배포용)

개발이 끝나고 다른 PC에 배포할 때:

```cmd
:: 1. PyInstaller 설치
pip install pyinstaller>=6.0

:: 2. 빌드
.venv\Scripts\pyinstaller.exe OctHitlEditor.spec --clean --noconfirm

:: 또는 편의 스크립트
build_windows.bat
```

출력: `dist\OctHitlEditor\OctHitlEditor.exe` (~250MB onedir 번들)

상세: `docs\build_standalone.md` 참고.

---

## 7. 프로젝트 구조

```
mouse_retinal_analysis\
├── src\
│   ├── io_utils.py          ← TIFF 로딩, B-scan 레이아웃 검출
│   ├── oct_analyzer.py      ← Boundary 검출 알고리즘 (TOP/ONL/BM/DET)
│   ├── viz.py               ← Overlay PNG 렌더링
│   ├── gt_guided.py         ← GT annotation TIFF 파싱
│   ├── batch_process.py     ← 폴더 단위 일괄 처리
│   ├── analyze_single.py    ← 단일 이미지 분석
│   └── hitl\                ← HITL 에디터 (PySide6 GUI)
│       ├── main.py          ← 엔트리포인트
│       ├── app.py           ← MainWindow
│       ├── canvas.py        ← 편집 캔버스
│       ├── sidebar.py       ← 파일 목록
│       ├── boundary_model.py ← BoundaryEditor
│       ├── boundary_toggle.py ← 가시성 체크박스
│       ├── colors.py        ← 색상 단일 소스
│       ├── db.py            ← SQLite 저장소
│       ├── storage.py       ← xlsx I/O
│       ├── overlay_render.py ← 보정 overlay PNG
│       ├── export_annotations.py ← CSV/TIFF export
│       ├── convert_annotations.py ← legacy → HITL 색상
│       └── batch_runner.py  ← 백그라운드 워커
├── tests\hitl\              ← pytest + pytest-qt 테스트 (60+)
├── docs\
│   ├── hitl_flow.md         ← 시스템 동작 원리
│   └── build_standalone.md  ← 빌드 가이드
├── data\mouse_data_org\     ← OCT TIFF 데이터 (96장)
├── OctHitlEditor.spec       ← PyInstaller 스펙
├── build_windows.bat        ← 빌드 편의 스크립트
├── requirements.txt
├── user_manual.md           ← 사용자 매뉴얼
├── new_dataset_guide.md     ← 새 데이터셋 가이드
└── dev_setup.md             ← 이 문서
```

---

## 8. 자주 쓰는 명령어 모음

```cmd
:: 환경
.venv\Scripts\activate                    :: venv 활성화 (CMD)
.venv\Scripts\Activate.ps1                :: PowerShell
deactivate                                 :: 비활성화

:: 실행
python -m src.hitl.main                   :: GUI
python -m src.batch_process <folder>       :: 일괄 분석
python -m src.analyze_single <file.tif>   :: 단일 이미지

:: 테스트
python -m pytest tests/hitl -v             :: 전체
python -m pytest tests/hitl/test_db.py     :: 특정 파일
python -m pytest -k "test_save"            :: 이름 매칭

:: 의존성
pip install -r requirements.txt           :: 일반
pip install -r requirements.txt --upgrade :: 업그레이드
pip freeze > requirements_lock.txt        :: 현재 버전 고정

:: 빌드
build_windows.bat                          :: exe 빌드
```

---

## 9. 트러블슈팅

### `ModuleNotFoundError: No module named 'PySide6'`
venv 활성화 안 했거나 의존성 설치 안 됨. `pip install -r requirements.txt` 재실행.

### `Python 3.11.x not found`
```cmd
pyenv install 3.11.6
pyenv local 3.11.6
python -m venv .venv
```

### Test가 hang (멈춤)
일부 GUI 테스트가 Qt event loop와 충돌. offscreen 모드 시도:
```cmd
set QT_QPA_PLATFORM=offscreen && python -m pytest tests/hitl
```
그래도 안되면 `tests/hitl/test_app.py`의 특정 테스트 격리 실행.

### `oct_results.xlsx` 파일 잠김 (Excel에서 열어둠)
Excel 닫고 재시도. 코드는 `os.replace` atomic rename 사용.

### batch_process 실행 시 메모리 부족
한 이미지당 ~50MB 메모리 사용. 96장 일괄 처리 시 ~5GB 피크. 32-bit Python으로는 실행 불가, 반드시 64-bit.

### Import 순환 참조
HITL 모듈은 분리되어 있어 보통 발생 안 함. 만약 새 모듈 추가하면서 발생하면 의존 방향 다시 점검:
```
db ← app
storage ← db, app
canvas ← app
boundary_model ← canvas, db, storage, app
colors ← canvas, export_annotations
```
(왼쪽이 의존되는 쪽, 오른쪽이 의존하는 쪽)

---

## 10. 디버깅 팁

### print 디버깅
HITL 에디터는 `console=False`로 빌드되어 stdout 안 보이지만, 개발환경(`python -m src.hitl.main`)에서는 터미널에 그대로 출력됨.

### 로깅
필요 시 `logging` 추가:
```python
import logging
logging.basicConfig(level=logging.DEBUG, format='%(name)s: %(message)s')
log = logging.getLogger(__name__)
log.debug(f"Layout detected: left_x={layout.left_x}")
```

### PySide6 GUI 디버그
```cmd
:: Qt 디버그 메시지 활성화
set QT_DEBUG_PLUGINS=1
python -m src.hitl.main

:: GUI 상태 확인
python -c "from PySide6 import QtCore; print(QtCore.__version__)"
```

### SQLite DB 직접 보기
```cmd
:: sqlite3 CLI (Windows 별도 다운로드)
sqlite3 data\mouse_data_org\output\db\oct_results.db
sqlite> .tables
sqlite> SELECT * FROM images LIMIT 3;
sqlite> SELECT COUNT(*) FROM per_column WHERE corr_TOP_y IS NOT NULL;
sqlite> .quit
```

또는 Python:
```python
import sqlite3
conn = sqlite3.connect("data/mouse_data_org/output/db/oct_results.db")
for row in conn.execute("SELECT stem, COUNT(*) FROM per_column GROUP BY stem"):
    print(row)
```

---

## 11. 기여 가이드 (간단)

코드 수정 → 테스트 → 커밋 → push:

```cmd
:: 1. 새 브랜치 (선택)
git checkout -b feat/my-feature

:: 2. 수정 + 테스트
python -m pytest tests/hitl -v

:: 3. 커밋
git add <files>
git commit -m "feat: <설명>"

:: 4. push
git push origin feat/my-feature
:: 또는 main 직접 push
git push origin main
```

테스트 모두 통과 + 기능 동작 확인 후 커밋 권장.

---

## 추가 자료

- 시스템 동작 원리: `docs\hitl_flow.md`
- 빌드 상세: `docs\build_standalone.md`
- 사용자 매뉴얼: `user_manual.md`
- 새 데이터셋 가이드: `new_dataset_guide.md`
- 원본 알고리즘 스펙: `README_ANALYSIS_OCT.md`
