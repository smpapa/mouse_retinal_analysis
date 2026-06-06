# 연구 분석 방법론 (Methods)

의학 논문의 *Methods* 섹션에 그대로 또는 발췌해서 사용할 수 있도록 작성. 한국어 본문 + 영문 번역본 둘 다 수록. 약어/괄호 인용 형식은 투고 학술지 양식에 맞춰 조정.

---

## 1. 한국어 본문 (국내 학술지용)

### OCT 영상 획득 및 전처리

마우스 망막 OCT 영상은 Heidelberg Spectralis HRA+OCT 시스템(Heidelberg Engineering, Heidelberg, Germany)으로 획득하였다. 각 영상은 IR fundus 영역과 B-scan 패널이 좌우로 배치된 RGB TIFF (596 × 2032 pixel) 형식이다. 영상 좌측에는 시신경 유두 주변을 포함하는 원형 IR fundus와 함께 스캔 위치를 표시하는 녹색 마커가 표시되어 있으며, 우측에는 B-scan 단면 영상이 배치된다.

자체 개발한 Python 기반 파이프라인(`io_utils.py`)이 각 영상에서 B-scan 패널 영역을 자동으로 검출하였다. IR/B-scan 경계는 Heidelberg 시스템이 IR fundus 위에 그려놓은 순녹색(R<50, G>200, B<50) 스캔 마커의 끝점을 기준으로 추출하였다. 수평 스캔(H suffix)은 가로 마커 선의 우측 끝, 수직 스캔(V suffix)은 세로 마커 선의 하단 끝을 IR panel 변 길이로 사용하였으며, IR panel이 정사각형이라는 기하학적 관계에 의해 panel 우측 경계(= B-scan 좌측 경계)를 결정하였다. 마커 검출이 실패한 영상에 대해서는 컬럼별 어두운 픽셀 비율(픽셀 값 < 30) 분포에서 sustained run을 찾는 fallback 알고리즘을 적용하였다.

축척(scale)은 Heidelberg 시스템이 영상에 그려놓은 200 µm 표시 막대로부터 검출을 시도하였고, 검출이 불가한 영상은 동기기의 마우스 OCT 표준값(Y축 3.87 µm/pixel, X축 11.50 µm/pixel)을 적용하였다.

### 자동 boundary 검출 알고리즘

다섯 개의 망막 경계를 컬럼 단위(per-column)로 검출하였다: 내경계막(internal limiting membrane, ILM, *코드명 TOP*), 외핵층/외망상층 경계(outer plexiform/outer nuclear layer interface, *코드명 ONL*), Bruch 막(Bruch's membrane, *코드명 BM*), 망막박리(retinal detachment) 영역의 상하 경계(*코드명 DET top/bottom*).

각 컬럼의 휘도 프로파일에 대해 다음 절차를 수행하였다.

1. **수직 평활화**: 1차원 Gaussian filter (σ = 1.5 pixel) 적용으로 픽셀 단위 노이즈 억제.
2. **피크 검출**: `scipy.signal.find_peaks` 함수로 prominence ≥ 6.0, 피크 간 최소 거리 4 pixel, 영상 상단으로부터 40 pixel 마진 이내 피크는 라벨/경계 노이즈로 간주하여 제외. 이후 영상 column-wise 최대 피크 높이의 15% 이상, 그리고 중앙값 + 2 × MAD (median absolute deviation) 임계값을 동시에 만족하는 피크만 유지.
3. **BM 결정**: 망막 단면의 최하단 bright band peak를 BM peak로 지정. BM peak 하단의 휘도 envelope에서 (peak intensity − local floor) × 0.7 + floor 지점, 즉 휘도가 피크의 70%까지 감소하는 첫 지점을 BM 위치로 확정.
4. **TOP 결정**: BM peak로부터 위쪽으로 RETINA_HEIGHT_MAX = 110 pixel 범위 내의 모든 retinal complex peak를 추출한 후, 가장 위쪽 peak의 upper edge를 동일한 70% edge-fraction 방식으로 ILM으로 확정.
5. **ONL 결정**: 망막 complex peak들 사이의 valley(국소 최저값)를 찾고, valley와 인접 peak 사이의 가중평균 (0.6 × valley + 0.4 × peak)으로 OPL/ONL 경계를 추정. 추가로 (ONL − TOP) / (BM − TOP) 비율이 0.40 ~ 0.70 범위 안에 들어오도록 제약하여 잘못된 valley 선정을 방지.
6. **드리프트 보정**: 검출된 column 좌표열에 대해 51 pixel 윈도우의 rolling median 기반 outlier 검사 후 Savitzky-Golay filter (window 91, polynomial degree 3)로 평활화. Outlier 거부와 평활화를 3회 반복하여 최종 좌표 결정.
7. **시신경 유두 영역 처리**: 영상 상단 15% 영역에서 픽셀 값 ≥ 100인 컬럼이 수직으로 15 pixel 이상 연속되는 영역을 시신경 유두로 식별하고 좌우로 12 pixel씩 확장. 해당 영역의 boundary는 NaN으로 마스킹하여 알고리즘이 시신경 영역을 우회하도록 처리.
8. **망막박리(DET) 검출**: 휘도 envelope에서 깊이 ≥ 50 grayscale unit, 강도 ≤ 110의 dip을 보이는 영역을 cavity로 식별. 수평 길이 ≥ 30 pixel, 전체 측정 가능 컬럼의 4% 이상을 차지하는 cavity에 대해서만 DET top/bottom 경계를 산출. (DET 미검출 영상은 정상 망막으로 분류.)

좌우 절반은 시신경 유두 중심을 기준으로 독립적으로 처리하여, 시신경 영역에서 양측이 잘못 연결되는 문제를 방지하였다.

### 두께 측정값

각 컬럼의 boundary 좌표로부터 다음 세 두께 지표를 µm 단위로 산출하였다.

- **전체 망막 두께(total retinal thickness)** = (BM_y − TOP_y) × scale_um_per_px_y
- **외망막 두께(outer retinal thickness)** = (BM_y − ONL_y) × scale_um_per_px_y
- **박리 두께(detachment thickness)** = (DET_bottom_y − DET_top_y) × scale_um_per_px_y

NaN인 컬럼은 측정 불가로 처리하고 평균 계산 시 제외하였다.

### 인간 검수 및 보정 (Human-in-the-loop, HITL)

자동 검출 결과의 정확도와 임상적 타당성을 검증하기 위해 자체 개발한 PySide6 기반 데스크톱 에디터(*OCT HITL Editor*)로 모든 영상을 검토하였다. 에디터는 다음 기능을 제공한다.

- 자동 검출된 다섯 boundary를 영상 위에 색상 코드(빨강 TOP, 초록 ONL, 파랑 BM, 노랑 DET top, 마젠타 DET bot)로 표시.
- 마우스 paint-trace 드래그로 컬럼 단위 boundary 보정.
- 명백한 오검출 구간에 대한 erase(NaN 처리) 기능.
- 보정값을 SQLite 데이터베이스에 즉시 저장하며, 자동 검출값은 불변(immutable) 컬럼으로 별도 보존.
- 보정 컬럼만으로 두께 측정값을 재계산하는 effective-value 정책: 보정값이 있는 컬럼은 보정값을, 없는 컬럼은 자동값을 사용.

검수자는 안과 영상 판독 경험을 보유한 [숫자]명이었으며, 각 영상에 대해 (1) 자동 검출 boundary가 해부학적으로 타당한지, (2) 시신경 유두 주변의 경계 불연속이 적절히 처리되었는지, (3) 망막박리 영역의 cavity 경계가 정확한지를 평가하고 필요 시 수정하였다.

### 검증 (선택적: 정확도 평가용)

정확도 평가를 위해 Heidelberg 시스템이 자동 라벨링한 reference annotation TIFF (4H, 6H 시점 영상)과 비교하였다. 색상 마스크로 reference boundary 좌표를 추출한 후, 본 알고리즘 결과와의 컬럼별 절대 오차(|Δy| pixel)의 중앙값을 reference 정확도 지표로 산출하였다. *(보고할 결과 예: TOP 1.83 pixel, ONL 2.96 pixel, BM 0.98 pixel, n = 2)*

### 통계 분석

[연구 설계에 맞게 작성. 예시: 그룹별 평균 두께 비교는 Mann-Whitney U test 또는 t-test로 수행하며, 다중 비교 보정은 Bonferroni method를 적용하였다. p < 0.05를 통계적 유의로 간주하였다. 분석은 Python 3.11 (NumPy, SciPy, pandas)로 수행하였다.]

### 소프트웨어 및 재현성

본 연구에 사용된 영상 분석 파이프라인, HITL 보정 에디터, 검증 도구의 전체 소스 코드 및 학습용 어노테이션 데이터는 GitHub 공개 저장소(https://github.com/smpapa/mouse_retinal_analysis)에서 자유롭게 다운로드 가능하다. 분석은 Python 3.11.6, PySide6 6.11, NumPy, SciPy, pandas, openpyxl, PIL 환경에서 수행하였다.

---

## 2. English version (for international journal submission)

### OCT image acquisition and preprocessing

Mouse retinal OCT images were acquired with the Heidelberg Spectralis HRA+OCT system (Heidelberg Engineering, Heidelberg, Germany). Each image is a 596 × 2032 pixel RGB TIFF containing a circular IR fundus panel on the left, with green scan-position markers overlaid, and a corresponding B-scan cross-section on the right.

A custom Python pipeline (`io_utils.py`) automatically detected the B-scan panel region in each image. We extracted the IR/B-scan boundary from the pure-green (R<50, G>200, B<50) scan markers that the Heidelberg system overlays on the IR fundus. For horizontal scans (H suffix), the rightmost x-coordinate of the dominant horizontal green line defined the IR panel right edge; for vertical scans (V suffix), the bottommost y-coordinate of the dominant vertical green line defined the IR panel side length. Because the IR panel is square, both measurements yielded the same panel right edge — equivalent to the B-scan panel left edge. When marker detection failed, a fallback algorithm searched for the leftmost sustained column run with high dark-pixel fraction (pixel value < 30).

Image scale was extracted from the 200 µm reference bar embedded by the Heidelberg system; for images in which automatic detection failed, the device's nominal mouse OCT calibration (3.87 µm/pixel axial, 11.50 µm/pixel lateral) was applied.

### Automated boundary segmentation

We segmented five retinal boundaries column-by-column: the internal limiting membrane (ILM, denoted TOP), the outer plexiform/outer nuclear layer interface (ONL), Bruch's membrane (BM), and the upper and lower boundaries of retinal detachment cavities (DET top, DET bottom) where present.

For each column, the algorithm performed the following steps:

1. **Vertical smoothing.** A one-dimensional Gaussian filter (σ = 1.5 pixel) was applied to suppress per-pixel noise.
2. **Peak detection.** Bright peaks were identified using `scipy.signal.find_peaks` with minimum prominence 6.0, minimum inter-peak distance 4 pixel, and a 40-pixel margin from the image top to exclude label and border artefacts. Peaks shorter than 15% of the column's strongest peak, or below the median + 2 × MAD intensity threshold, were rejected.
3. **BM localisation.** The lowest bright band peak was designated the BM peak. We located the BM boundary as the first y-coordinate below the peak where the intensity envelope falls to 70% of (peak intensity − local floor), tracking the lower edge of the bright RPE/BM complex rather than the noisy half-maximum point.
4. **TOP localisation.** All retinal-complex peaks within 110 pixels above the BM peak were collected. The upper edge of the highest peak, computed by the same 70% edge-fraction method, defined TOP (ILM).
5. **ONL localisation.** Valleys (local minima) between the retinal complex peaks were located, and ONL was estimated as the weighted average 0.6 × valley + 0.4 × adjacent peak. We enforced the geometric constraint 0.40 ≤ (ONL − TOP) / (BM − TOP) ≤ 0.70 to reject spurious valley assignments.
6. **Drift correction.** The per-column boundary coordinates were screened for outliers within a 51-pixel rolling median window, then smoothed with a Savitzky-Golay filter (window 91, polynomial degree 3). Outlier rejection and smoothing were iterated three times.
7. **Optic disc handling.** Columns whose top 15% of pixels included a connected vertical bright run (intensity ≥ 100) of at least 15 pixels were classified as optic disc columns and dilated by 12 pixels on each side. Boundaries within this mask were set to NaN, preventing the algorithm from threading across the optic nerve head.
8. **Detachment detection.** Intensity envelopes were searched for cavities with depth ≥ 50 grayscale units and minimum intensity ≤ 110. Cavities spanning ≥ 30 pixels horizontally, and covering ≥ 4% of measurable columns, were classified as detachments and assigned DET top and DET bottom boundaries; otherwise the image was classified as non-detached retina.

The left and right halves of each B-scan, separated at the optic disc centre, were processed independently to avoid spurious connections across the nerve head.

### Thickness measurements

Per-column thickness measurements were computed as

- **Total retinal thickness** = (BM_y − TOP_y) × scale_um_per_px_y
- **Outer retinal thickness** = (BM_y − ONL_y) × scale_um_per_px_y
- **Detachment thickness** = (DET_bottom_y − DET_top_y) × scale_um_per_px_y

NaN columns were excluded from per-image mean thickness calculations.

### Human-in-the-loop (HITL) review and correction

To validate the automated segmentation and ensure clinical accuracy, all images were reviewed in a custom PySide6 desktop editor (*OCT HITL Editor*). The editor displays the five automatic boundaries as colour-coded lines (red TOP, green ONL, blue BM, yellow DET top, magenta DET bottom) overlaid on the original B-scan, and allows reviewers to:

- Correct individual boundaries column-by-column via paint-trace mouse drag, with linear interpolation between successive cursor positions.
- Erase obviously erroneous segments (e.g. unrealistic spikes), setting the affected columns to NaN.
- Save corrections immediately to a local SQLite database, preserving the original automatic values in immutable columns.

Final thickness values were computed from *effective boundaries*: corrected when a reviewer edit existed for that column, and automatic otherwise. This dual-column design preserves the original detection results for inter-method comparison while allowing manual correction where required.

Image review was performed by [N] reviewers with experience in ophthalmic image interpretation. Each image was assessed for (1) anatomical plausibility of the automatic boundaries, (2) correct handling of discontinuities around the optic nerve head, and (3) accuracy of detachment cavity boundaries, with corrections applied as needed.

### Accuracy assessment (optional, where reference is available)

For a subset of images with corresponding Heidelberg-generated reference annotations, accuracy was assessed by comparing each automatic boundary against the reference. Reference coordinates were extracted from the annotation TIFFs using colour-mask segmentation, and per-column absolute errors |Δy| (pixel) were summarised by their median. *(Example baseline results: TOP 1.83 pixel, ONL 2.96 pixel, BM 0.98 pixel, n = 2.)*

### Statistical analysis

[Insert as appropriate, for example:] Group thickness comparisons used the Mann–Whitney U test, with Bonferroni correction for multiple testing. A *p*-value < 0.05 was considered statistically significant. All analyses were performed in Python 3.11 (NumPy, SciPy, pandas).

### Software and reproducibility

The complete analysis pipeline, HITL correction editor, validation tools, and training-set annotations are publicly available at https://github.com/smpapa/mouse_retinal_analysis. Analyses were performed in Python 3.11.6 with PySide6 6.11, NumPy, SciPy, pandas, openpyxl, and Pillow.

---

## 3. 작성 시 채워야 할 항목 (placeholder check-list)

논문 투고 전 다음 항목들을 본인 연구에 맞게 확정:

- [ ] 동물 모델: 마우스 종류, 나이, 성별, 사육 조건, IACUC/IRB 승인 번호
- [ ] OCT 촬영 조건: 영상 모드 (HR / HS), ART 횟수, 신호 품질 Q 임계값, 마취 protocol
- [ ] 데이터셋 규모: 총 영상 수 (n = ?), 시점/날짜 분포, 군별 분포
- [ ] 검수자 수 및 자격
- [ ] 통계 방법 (연구 설계에 따라)
- [ ] 윤리 승인 사항 / 자금 출처 / 이해 상충 (별도 섹션 권장)
- [ ] Heidelberg 시스템 모델명 및 OS/Acquisition software 버전
- [ ] Reference annotation 검증 시: 검증 대상 영상 수, 검수자 일치도

---

## 4. 인용 권장 문헌 (선택적)

본 알고리즘의 핵심 기법 인용:
- Savitzky-Golay 평활화: Savitzky A, Golay MJE. *Anal Chem* 1964;36(8):1627-39.
- Peak prominence 기반 검출: scipy 공식 문헌 또는 Virtanen P et al. *Nat Methods* 2020;17(3):261-272.
- OCT 망막 분할 알고리즘 비교 시 본 방법론을 reference로 명시.

소프트웨어 인용:
- GitHub 저장소 인용 — Zenodo DOI 발급 후 DOI 형태로 표기 권장.

---

*문의: 알고리즘 상세나 추가 검증 결과 관련 문의는 GitHub 저장소 issues에 등록.*
