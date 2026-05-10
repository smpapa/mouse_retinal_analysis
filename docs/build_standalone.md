# Standalone Windows Build

**목표**: 파이썬이 설치되지 않은 PC에서도 OCT HITL Editor를 단독 실행할 수 있는 폴더를 만든다.

**도구**: PyInstaller (onedir 모드).

---

## 빌드

프로젝트 루트에서 `.venv`가 활성화된 상태로 실행:

```cmd
build_windows.bat
```

또는 수동:

```cmd
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller.exe OctHitlEditor.spec --clean --noconfirm
```

빌드 시간: 약 1–3분. 완료 후 다음 산출물이 생성된다:

```
dist/
└── OctHitlEditor/
    ├── OctHitlEditor.exe        ← 실행 파일
    ├── _internal/
    │   ├── PySide6/             (Qt 런타임)
    │   ├── numpy/               (네이티브 라이브러리)
    │   ├── scipy/
    │   ├── ...                  (총 200–400MB)
    │   └── *.dll
    └── ...
```

`OctHitlEditor.exe`만 실행해도 되지만 같은 폴더의 `_internal/` 디렉터리가 반드시 옆에 있어야 한다.

---

## 배포

**전체 폴더를 zip으로 묶어서 전달**:

```cmd
powershell Compress-Archive -Path dist\OctHitlEditor\* -DestinationPath OctHitlEditor.zip
```

대상 PC에서:

1. zip을 임의의 폴더(예: `C:\Tools\OctHitlEditor`)에 압축 해제
2. `OctHitlEditor.exe` 더블클릭 또는 바로가기 생성

파이썬, PySide6, numpy 등 사전 설치 불필요.

---

## 사용 흐름 (대상 PC)

1. `OctHitlEditor.exe` 실행 → 빈 사이드바로 시작 (워크북 미지정)
2. **File > Open Data Folder...** 클릭 → TIFF가 들어 있는 폴더 선택
   - 해당 폴더 안에 `output/oct_results.xlsx`가 이미 있으면 자동 로드
   - 없으면 "Run auto analysis now?" 프롬프트 → **Yes**
3. `Tools > Run Auto Analysis...`을 직접 호출해도 같다 — 진행 상황은 다이얼로그로 표시
4. 완료 후 사이드바에 파일 목록 채워짐 → 편집 시작

---

## 트러블슈팅

| 증상 | 해결 |
|---|---|
| `OctHitlEditor.exe` 실행 시 즉시 종료 | 같은 폴더에 `_internal/`이 함께 있는지 확인. zip 해제가 부분적으로 됐을 수 있음 |
| `ImportError: DLL load failed` | Visual C++ Redistributable 14.x 필요. Microsoft 공식 사이트에서 설치 |
| 첫 실행이 느림 (10초+) | 정상. Windows Defender의 첫 스캔 + 각종 DLL 로드. 두 번째부터는 빠르다 |
| `OSError: [WinError 32] ... oct_results.xlsx` | Excel이 워크북을 잡고 있음. Excel 닫고 재시도 |
| 자동 분석 중 GUI 멈춤 | 정상이 아님 — 워커 스레드 문제. `dist/OctHitlEditor`를 cmd에서 직접 실행해 stderr 확인 |

---

## 빌드 옵션 변경

`OctHitlEditor.spec`에서:

- **`console=False`** → `True`로 바꾸면 .exe 실행 시 콘솔창이 함께 뜬다 (디버그용)
- **`excludes=[...]`** 항목 — 더 작은 빌드를 원하면 추가
- **`upx=False`** → `True`로 바꾸고 UPX를 PATH에 두면 binary 압축 (시작 약간 느려짐)

`--onefile` 모드로 빌드하려면 `EXE`/`COLLECT` 부분을 PyInstaller `--onefile` 템플릿으로 교체. 단점: 매 실행마다 `%TEMP%`에 압축 해제하므로 시작이 5–15초 느려짐. 연구용 GUI에는 onedir(현재 모드)이 권장.

---

## 빌드 산출물 git 제외

`.gitignore`에 `build/`, `dist/`가 이미 있어 자동으로 제외된다. 커밋하지 말 것.
