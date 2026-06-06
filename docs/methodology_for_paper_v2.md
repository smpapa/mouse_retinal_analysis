# 연구 분석 방법론 v2 — HITL 기반 알고리즘 정밀화 (Methods, expanded)

`methodology_for_paper.md`의 확장판. 자동 boundary 검출의 1차 결과를 HITL 검수에서 끝내지 않고, 검수에서 얻은 보정 데이터를 다시 알고리즘 정밀화에 환류시키는 **feedback loop 방법론**을 추가로 기술. 1차 문서가 *"무엇을 검출했는가"*를 다룬다면 본 문서는 *"검출을 어떻게 더 정확하게 만들었는가"*를 다룬다.

목차:
1. 한국어 본문 (국내 학술지용)
2. English version (international journal)
3. 부록: feedback loop 운영 기록 양식

---

## 1. 한국어 본문 (국내 학술지용)

### 1.1 OCT 영상 획득 및 전처리

마우스 망막 OCT 영상은 Heidelberg Spectralis HRA+OCT 시스템(Heidelberg Engineering, Heidelberg, Germany)으로 획득하였다. 각 영상은 IR fundus 영역과 B-scan 패널이 좌우로 배치된 RGB TIFF (596 × 2032 pixel) 형식이다. 영상 좌측에는 시신경 유두 주변을 포함하는 원형 IR fundus와 함께 스캔 위치를 표시하는 녹색 마커가 표시되어 있으며, 우측에는 B-scan 단면 영상이 배치된다.

자체 개발한 Python 기반 파이프라인(`io_utils.py`)이 각 영상에서 B-scan 패널 영역을 자동으로 검출하였다. IR/B-scan 경계는 Heidelberg 시스템이 IR fundus 위에 그려놓은 순녹색(R<50, G>200, B<50) 스캔 마커의 끝점을 기준으로 추출하였다. 수평 스캔(H suffix)은 가로 마커 선의 우측 끝, 수직 스캔(V suffix)은 세로 마커 선의 하단 끝을 IR panel 변 길이로 사용하였으며, IR panel이 정사각형이라는 기하학적 관계에 의해 panel 우측 경계(= B-scan 좌측 경계)를 결정하였다. 마커 검출이 실패한 영상에 대해서는 컬럼별 어두운 픽셀 비율(픽셀 값 < 30) 분포에서 sustained run을 찾는 fallback 알고리즘을 적용하였다.

축척(scale)은 Heidelberg 시스템이 영상에 그려놓은 200 µm 표시 막대로부터 검출을 시도하였고, 검출이 불가한 영상은 동기기의 마우스 OCT 표준값(Y축 3.87 µm/pixel, X축 11.50 µm/pixel)을 적용하였다.

### 1.2 자동 boundary 검출 알고리즘 (1차)

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

### 1.3 HITL 기반 보정 데이터 수집

자동 알고리즘 출력에 대한 검수 및 보정은 자체 개발한 PySide6 데스크톱 에디터(*OCT HITL Editor*)에서 수행하였다. 본 에디터의 보정 모델은 **자동값(immutable)과 보정값(corrected)을 별도 컬럼으로 보존**하는 dual-column 구조를 채택하였다. 이 구조는 두 가지 목적을 동시에 충족한다.

- *연구 결과*: 보정값을 적용한 effective boundary로 최종 두께 측정.
- *알고리즘 개선*: 자동값과 보정값의 차이 벡터(Δy = corrected − auto)를 모든 컬럼에 대해 산출 가능. 이는 자동 알고리즘의 **컬럼 단위 오차 ground truth**가 된다.

검수자는 paint-trace 드래그로 boundary를 컬럼 단위로 보정하고, 명백한 오검출 구간은 erase(NaN)로 처리하였다. 모든 편집 이벤트는 SQLite 데이터베이스에 즉시 기록되며, image stem · boundary type · column · auto_y · corrected_y · timestamp · reviewer_id가 한 행으로 저장된다.

### 1.4 보정 데이터를 활용한 알고리즘 정밀화 방법론

본 연구는 HITL 보정 데이터를 단순한 품질 검증을 넘어 알고리즘 파라미터 최적화의 ground truth로 활용하였다. 정밀화 절차는 다음 5단계 cycle로 구성된다.

#### Step 1. 오차 패턴 분석 (error stratification)

DB에 누적된 (auto_y, corrected_y) 쌍을 다음 축으로 분층 분석하였다.

- **Boundary type별** (TOP / ONL / BM / DET): boundary마다 실패 양상이 다름.
- **영상 위치별**: 시신경 유두 인접 (±150 px), 변연부 (좌·우 끝 10%), 중심부.
- **스캔 방향별**: H scan vs V scan (마커 검출 결과에 따라 layout이 다르므로 영향이 다름).
- **검출 모드별**: peak이 정상 검출된 컬럼, valley 비율 제약에 의해 reject된 컬럼, drift 보정으로 큰 폭으로 이동된 컬럼.

각 분층에서 |Δy|의 중앙값과 75-percentile을 산출하여 **알고리즘이 체계적으로 실패하는 영역(systematic failure modes)**을 정량적으로 식별하였다.

#### Step 2. 실패 양상 분류 (failure mode taxonomy)

육안 검수에서 확인된 오류 양상을 다음 다섯 범주로 분류하였다.

| 범주 | 정의 | 알고리즘 책임 단계 |
|---|---|---|
| **(a) Peak miss** | 진짜 boundary peak가 prominence/height threshold에 의해 reject | §1.2 step 2 (peak detection) |
| **(b) Wrong peak** | 잘못된 peak (예: 반사 노이즈)가 boundary로 선택 | §1.2 step 3·4 (BM/TOP 결정) |
| **(c) Edge offset** | Peak 위치는 맞으나 70% edge-fraction에서 시스템적으로 1–3 px 어긋남 | §1.2 step 3·4 (edge fraction) |
| **(d) ONL 비율 위반** | 0.40–0.70 비율 제약이 너무 좁아 정상 valley가 reject | §1.2 step 5 (ONL 결정) |
| **(e) 시신경 유두 누락/과확장** | Optic disc 마스크 ±12 px이 실제 disc 폭과 불일치 | §1.2 step 7 (disc handling) |

분류는 검수자가 보정 시점에 메모(`note` 필드)로 입력하거나, 사후에 자동 vs 보정 차이의 통계 특성으로 inferred되도록 설계하였다.

#### Step 3. 파라미터 sweep 및 재실행

식별된 실패 양상에 대응하는 알고리즘 파라미터를 다음과 같이 mapping하여 candidate 값 set를 sweep 하였다.

- (a) Peak miss → PEAK_MIN_PROMINENCE ∈ {3, 4, 5, 6, 7}, PEAK_HEIGHT_K_MAD ∈ {1.5, 2.0, 2.5}
- (b) Wrong peak → RETINA_HEIGHT_MAX_PX ∈ {90, 100, 110, 120}, NEIGHBOUR_DELTA_PX ∈ {15, 20, 25}
- (c) Edge offset → EDGE_FRAC ∈ {0.5, 0.6, 0.7, 0.8}, DET_EDGE_FRAC ∈ {0.4, 0.5, 0.6}
- (d) ONL 비율 → ONL 가중치 (valley·peak ratio) ∈ {(0.5, 0.5), (0.6, 0.4), (0.7, 0.3)}, 비율 제약 ∈ {(0.35–0.75), (0.40–0.70), (0.45–0.65)}
- (e) Disc 처리 → DISC_BRIGHT_THRESH ∈ {80, 100, 120}, DISC_DILATE_PX ∈ {8, 12, 16}

각 candidate 조합으로 전체 데이터셋을 재처리한 결과 boundary 좌표열을, HITL 보정값을 ground truth로 하여 다음 두 metric으로 평가하였다.

- **MAE_per_boundary** = median over columns of |y_auto − y_corrected| (pixel)
- **Failure rate** = boundary 별 |Δy| > 5 pixel인 컬럼 비율 (%)

#### Step 4. 파라미터 선택 기준

다음 우선순위로 best parameter set를 선택하였다.

1. **임상적 의미 우선**: BM·TOP의 MAE를 ONL의 MAE보다 우선시. (총 망막 두께는 BM·TOP 정확도에 직접 의존.)
2. **꼬리(tail) 억제**: median이 낮더라도 failure rate가 높은 candidate는 reject. (소수 영상의 catastrophic error가 평균 두께를 왜곡.)
3. **재현성**: 인접 파라미터 ±10% 변동 시 metric 안정 (plateau on parameter surface).
4. **Occam's razor**: 동등 성능이면 default에 가까운 값 선호 (overfit 방지).

#### Step 5. 잔여 오차 검증 및 cycle 반복

새 파라미터로 재실행한 결과를 다시 HITL 에디터로 검수하여, (1) systematic error가 제거되었는지, (2) 새로운 실패 양상이 도입되지 않았는지 확인하였다. 잔여 오차가 임상적 허용 범위(BM·TOP 중앙값 ≤ 2 px, ONL 중앙값 ≤ 3 px, failure rate ≤ 5%) 안에 들어올 때까지 본 cycle을 반복하였다.

본 연구에서는 [N] 회의 cycle 후 위 기준을 만족하는 파라미터 set에 수렴하였다. (보고할 결과 예: TOP 중앙값 1.83 → 1.21 pixel, ONL 2.96 → 2.04 pixel, BM 0.98 → 0.74 pixel, 5-pixel failure rate 8.4% → 3.1%.)

### 1.5 Dual-column 저장 구조의 의의

본 방법론의 핵심은 자동값과 보정값을 동시에 보존하는 dual-column 설계에 있다. 이 설계는 다음 세 가지 기여를 한다.

- **재현성**: 알고리즘 파라미터를 변경해도 자동값 컬럼을 갱신할 뿐 보정값은 보존되므로, 동일 ground truth로 여러 파라미터 set를 공정하게 비교 가능.
- **불변성(audit trail)**: 최종 publication-grade 두께 측정값이 보정값에 기반하더라도, 원래 자동값이 모든 컬럼에 기록되어 있어 사후 감사(post-hoc audit)가 가능.
- **데이터셋 가치**: 본 연구에서 누적한 (image, column, auto_y, corrected_y) 쌍은 후속 연구의 supervised learning training data로 그대로 활용 가능. (예: U-Net 기반 segmentation 모델의 fine-tuning ground truth.)

### 1.6 두께 측정 및 통계 분석

각 컬럼의 effective boundary 좌표로부터 다음 세 두께 지표를 µm 단위로 산출하였다.

- **전체 망막 두께(total retinal thickness)** = (BM_y − TOP_y) × scale_um_per_px_y
- **외망막 두께(outer retinal thickness)** = (BM_y − ONL_y) × scale_um_per_px_y
- **박리 두께(detachment thickness)** = (DET_bottom_y − DET_top_y) × scale_um_per_px_y

NaN인 컬럼은 측정 불가로 처리하고 평균 계산 시 제외하였다. 그룹별 평균 두께 비교는 Mann-Whitney U test 또는 t-test로 수행하며, 다중 비교 보정은 Bonferroni method를 적용하였다. p < 0.05를 통계적 유의로 간주하였다. 분석은 Python 3.11 (NumPy, SciPy, pandas)로 수행하였다.

### 1.7 소프트웨어 및 재현성

본 연구의 영상 분석 파이프라인, HITL 에디터, 파라미터 sweep 스크립트, dual-column SQLite 스키마는 GitHub 공개 저장소(https://github.com/smpapa/mouse_retinal_analysis)에서 자유롭게 다운로드 가능하다. 모든 cycle의 파라미터 set과 metric은 `docs/parameter_history.md`에 시간 순으로 기록하여 정밀화 과정 전체가 재현 가능하도록 하였다. 분석은 Python 3.11.6, PySide6 6.11, NumPy, SciPy, pandas, openpyxl, Pillow 환경에서 수행하였다.

---

## 2. English version (for international journal submission)

### 2.1 OCT image acquisition and preprocessing

Mouse retinal OCT images were acquired with the Heidelberg Spectralis HRA+OCT system (Heidelberg Engineering, Heidelberg, Germany). Each image is a 596 × 2032 pixel RGB TIFF containing a circular IR fundus panel on the left, with green scan-position markers overlaid, and a corresponding B-scan cross-section on the right.

A custom Python pipeline (`io_utils.py`) automatically detected the B-scan panel region in each image. We extracted the IR/B-scan boundary from the pure-green (R<50, G>200, B<50) scan markers that the Heidelberg system overlays on the IR fundus. For horizontal scans (H suffix), the rightmost x-coordinate of the dominant horizontal green line defined the IR panel right edge; for vertical scans (V suffix), the bottommost y-coordinate of the dominant vertical green line defined the IR panel side length. Because the IR panel is square, both measurements yielded the same panel right edge — equivalent to the B-scan panel left edge. When marker detection failed, a fallback algorithm searched for the leftmost sustained column run with high dark-pixel fraction (pixel value < 30).

Image scale was extracted from the 200 µm reference bar embedded by the Heidelberg system; for images in which automatic detection failed, the device's nominal mouse OCT calibration (3.87 µm/pixel axial, 11.50 µm/pixel lateral) was applied.

### 2.2 Initial automated boundary segmentation

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

### 2.3 HITL correction data collection

Boundary review and correction were performed in a custom PySide6 editor (*OCT HITL Editor*) that adopts a **dual-column data model**: each per-column boundary value is stored both as an immutable `auto_y` (algorithm output) and a `corrected_y` (reviewer edit, NULL if untouched). This dual-column design serves two purposes simultaneously:

- *For the study results*: effective boundary = corrected_y if present, else auto_y; final thickness measurements are computed from effective boundaries.
- *For algorithm refinement*: the per-column residual Δy = corrected_y − auto_y provides a column-level ground truth for the algorithm's error.

Reviewers corrected boundaries column-by-column via paint-trace mouse drag and erased clearly erroneous segments by setting the affected columns to NaN. Every edit event was logged to a SQLite database with image stem, boundary type, column index, auto_y, corrected_y, timestamp, and reviewer ID.

### 2.4 HITL-driven algorithm refinement methodology

We treated the accumulated correction data not as a one-time QC pass but as a **feedback signal for systematic algorithm refinement**. The refinement procedure consisted of a five-step cycle.

#### Step 1. Error stratification

The corpus of (auto_y, corrected_y) pairs was stratified along four axes — boundary type (TOP / ONL / BM / DET), spatial location (peri-optic-disc within ±150 px, peripheral 10%, central), scan orientation (H vs V), and algorithm sub-stage (peaks that passed detection, columns rejected by ONL ratio constraint, columns shifted by drift correction). Within each stratum we computed the median and 75th-percentile of |Δy| to identify **systematic failure modes** quantitatively.

#### Step 2. Failure mode taxonomy

Five failure categories were defined, each traceable to a specific algorithm stage:

| Category | Definition | Owning stage |
|---|---|---|
| **(a) Peak miss** | True boundary peak rejected by prominence/height threshold | peak detection |
| **(b) Wrong peak** | A spurious peak (e.g. reflection artefact) selected as boundary | BM / TOP localisation |
| **(c) Edge offset** | Peak position correct but 70% edge-fraction systematically off by 1–3 px | edge-fraction step |
| **(d) ONL ratio violation** | The 0.40–0.70 constraint too tight, rejecting valid valleys | ONL localisation |
| **(e) Disc mask error** | The ±12 px optic disc dilation mismatched the actual disc width | optic disc handling |

Categories were either entered by reviewers as a free-text `note` field at correction time or inferred post-hoc from the statistical signature of the auto-vs-corrected difference.

#### Step 3. Parameter sweep and re-run

Each failure category was mapped to one or more algorithm parameters, and candidate values were swept:

- (a) Peak miss → PEAK_MIN_PROMINENCE ∈ {3, 4, 5, 6, 7}; PEAK_HEIGHT_K_MAD ∈ {1.5, 2.0, 2.5}
- (b) Wrong peak → RETINA_HEIGHT_MAX_PX ∈ {90, 100, 110, 120}; NEIGHBOUR_DELTA_PX ∈ {15, 20, 25}
- (c) Edge offset → EDGE_FRAC ∈ {0.5, 0.6, 0.7, 0.8}; DET_EDGE_FRAC ∈ {0.4, 0.5, 0.6}
- (d) ONL ratio → valley/peak weights ∈ {(0.5, 0.5), (0.6, 0.4), (0.7, 0.3)}; ratio bounds ∈ {(0.35–0.75), (0.40–0.70), (0.45–0.65)}
- (e) Disc handling → DISC_BRIGHT_THRESH ∈ {80, 100, 120}; DISC_DILATE_PX ∈ {8, 12, 16}

For each candidate parameter set, the entire dataset was re-processed and the resulting boundary coordinates were evaluated against the HITL correction ground truth using

- **MAE_per_boundary** = median over columns of |y_auto − y_corrected| (pixel),
- **Failure rate** = fraction of columns where |Δy| > 5 pixel.

#### Step 4. Parameter selection criteria

The best parameter set was selected by the following priority:

1. **Clinical priority**: minimise BM and TOP MAE before ONL MAE — total retinal thickness depends directly on BM/TOP accuracy.
2. **Tail suppression**: reject candidates with low median but high failure rate — catastrophic errors on a few images distort group means.
3. **Stability**: prefer parameter values lying on a plateau (metric stable to ±10% perturbation) — guards against fragile choices.
4. **Occam's razor**: when performance ties, prefer values close to the defaults to avoid overfitting.

#### Step 5. Residual verification and iteration

The refined parameter set was applied to the dataset, and outputs were reviewed again in the HITL editor to confirm (1) that the targeted systematic errors had been eliminated and (2) that no new failure modes had emerged. The cycle was repeated until residual errors met clinical tolerance — BM and TOP medians ≤ 2 pixel, ONL median ≤ 3 pixel, and 5-pixel failure rate ≤ 5%.

In this study, the cycle converged after [N] iterations. *(Example: TOP median 1.83 → 1.21 px, ONL 2.96 → 2.04 px, BM 0.98 → 0.74 px; 5-pixel failure rate 8.4% → 3.1%.)*

### 2.5 Significance of the dual-column design

The dual-column storage of auto and corrected values is central to this methodology. It provides:

- **Reproducibility.** Updating algorithm parameters refreshes only the auto column; corrections persist, so multiple parameter sets can be compared against the same ground truth.
- **Auditability.** Even though final publication-grade thicknesses derive from corrected values, the original auto values remain on record for every column, enabling post-hoc audit.
- **Dataset value.** The accumulated (image, column, auto_y, corrected_y) tuples constitute a labelled training set directly usable for downstream supervised learning (e.g. U-Net fine-tuning for retinal layer segmentation).

### 2.6 Thickness measurement and statistical analysis

Per-column thickness measurements were computed from effective boundaries as

- **Total retinal thickness** = (BM_y − TOP_y) × scale_um_per_px_y
- **Outer retinal thickness** = (BM_y − ONL_y) × scale_um_per_px_y
- **Detachment thickness** = (DET_bottom_y − DET_top_y) × scale_um_per_px_y

NaN columns were excluded from per-image mean thickness calculations. Group thickness comparisons used the Mann–Whitney U test, with Bonferroni correction for multiple testing. A *p*-value < 0.05 was considered statistically significant. All analyses were performed in Python 3.11 (NumPy, SciPy, pandas).

### 2.7 Software and reproducibility

The analysis pipeline, HITL editor, parameter-sweep scripts, and dual-column SQLite schema are publicly available at https://github.com/smpapa/mouse_retinal_analysis. All cycle parameter sets and corresponding metrics are logged chronologically in `docs/parameter_history.md`, making the full refinement trajectory reproducible. Analyses were performed with Python 3.11.6, PySide6 6.11, NumPy, SciPy, pandas, openpyxl, and Pillow.

---

## 3. 부록 — Feedback loop 운영 기록 양식

논문에 표/supplementary로 첨부 가능한 형태의 cycle 기록 양식. 실제 cycle 수행 후 빈칸을 채워 supplementary table로 사용.

### 3.1 Parameter history table (supplementary)

| Cycle | Date | Triggered by failure mode | Changed parameter(s) | TOP median (px) | ONL median (px) | BM median (px) | 5-px failure rate (%) | Notes |
|---|---|---|---|---|---|---|---|---|
| 0 (baseline) | YYYY-MM-DD | — | defaults | 1.83 | 2.96 | 0.98 | 8.4 | initial release |
| 1 | YYYY-MM-DD | (c) Edge offset | EDGE_FRAC 0.7 → 0.65 | ... | ... | ... | ... | ... |
| 2 | YYYY-MM-DD | (d) ONL ratio | bounds 0.40–0.70 → 0.38–0.72 | ... | ... | ... | ... | ... |
| ... | | | | | | | | |
| final | YYYY-MM-DD | — | accepted | 1.21 | 2.04 | 0.74 | 3.1 | clinical tolerance met |

### 3.2 Reviewer-correction summary (supplementary)

| Image set | n images | n columns reviewed | n columns corrected | Correction rate (%) | Reviewer agreement κ |
|---|---|---|---|---|---|
| Training (4H/6H subset) | ... | ... | ... | ... | ... |
| Validation | ... | ... | ... | ... | ... |
| Held-out test | ... | ... | ... | ... | ... |

### 3.3 Failure-mode distribution (supplementary)

각 cycle에서 발견된 실패 양상의 비율을 stacked bar chart로 시각화. 횟수 누적이 cycle을 거치며 어떤 양상이 해결되고 어떤 양상이 잔존했는지 보여줌. (Figure SX 후보.)

---

## 4. v1과의 관계 정리

| 항목 | v1 (`methodology_for_paper.md`) | v2 (본 문서) |
|---|---|---|
| 자동 알고리즘 기술 | ✔ (전체) | 참조만 (요약) |
| HITL 검수 워크플로 | ✔ | ✔ (확장) |
| Dual-column 보존 | 언급 | 별도 절로 의의 기술 |
| 파라미터 sweep / cycle | — | ✔ (§1.4 / §2.4) |
| 실패 양상 분류 (taxonomy) | — | ✔ |
| Supplementary 양식 | — | ✔ (§3) |
| 후속 ML 데이터셋 가치 | — | ✔ |

투고 학술지 성격에 따라 선택 사용:

- **임상 연구 위주 학술지** (망막 질환, 전임상 모델 등) → v1을 본문, v2 §3 supplementary table만 부록으로.
- **방법론·이미지 분석 학술지** (medical image analysis 계열) → v2를 본문, v1 §검증 결과만 발췌.

---

*문의: feedback cycle의 raw data 또는 추가 분층 분석은 GitHub 저장소 issues에 등록.*
