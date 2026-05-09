# OCT Analysis Guide

이 문서는 현재 프로젝트에서 사용하는 OCT 분석 기준을 정리한 문서입니다.  
특히 아래 두 가지를 기준으로 작성했습니다.

- 경계 정의는 사용자가 최종 합의한 정의를 그대로 따른다.
- 4H / 6H annotation 파일은 GT(ground truth) 예시로 사용하되, 다른 이미지에도 같은 규칙이 일반화되어야 한다.

관련 코드:

- [analysis_oct_03.py](/D:/workspace/sumin/src/analysis_oct_03.py)
- [batch_gt_guided_processing.py](/D:/workspace/sumin/src/batch_gt_guided_processing.py)

관련 GT 예시:

- [21_OS_4H_annotation.tiff](/D:/workspace/sumin/data/mouse_data_org/annotation/21_OS_4H_annotation.tiff)
- [21_OS_6H_annotation.tiff](/D:/workspace/sumin/data/mouse_data_org/annotation/21_OS_6H_annotation.tiff)

## 목적

이 프로젝트의 목적은 Heidelberg OCT 합성 TIFF에서 다음 정보를 일관된 규칙으로 추출하는 것입니다.

- `TOP` 경계
- `ONL` 경계
- `BM` 경계
- detachment 유무
- detachment가 있을 경우 `DET top / DET bottom`
- 중심 기준 좌우 위치
- 각 위치에서의 두께 측정값

## 입력 이미지 구조

입력 TIFF는 보통 다음 구조를 가집니다.

1. 왼쪽: IR image
2. 오른쪽: B-scan image

예시:

- [21_OS_4H.tif](/D:/workspace/sumin/data/mouse_data_org/21_OS_4H.tif)
- [21_OS_6H.tif](/D:/workspace/sumin/data/mouse_data_org/21_OS_6H.tif)

## 최종 경계 정의

아래 정의는 이 프로젝트에서 가장 중요한 기준입니다.

### BM

`BM`은 **가장 아래쪽에 있는 선명한 흰색 bright band의 아래 경계**입니다.

즉,

- 가장 아래 bright white band를 찾고
- 그 band의 `lower boundary`를 BM으로 사용합니다.

### ONL

`ONL`은 **BM 영역 바로 위쪽에서 식별되는 흰색 band의 윗경계**입니다.

즉,

- BM 바로 위의 흰색 band를 찾고
- 그 band의 `upper boundary`를 ONL로 사용합니다.

주의:

- ONL은 BM 자체의 윗경계가 아닙니다.
- ONL은 BM보다 위에 있는 별도의 흰색선의 윗경계입니다.

### TOP

`TOP`은 **새까만 vitreous 직전의 마지막 흰색 경계**입니다.

즉,

- 위쪽 retinal bright complex를 찾고
- 그 band의 가장 위 경계를 TOP으로 사용합니다.

## Detachment 정의

`DETACHMENT`는 **ONL과 BM 사이에 생긴 저반사(hyporeflective) 검은 cavity**입니다.

즉,

- detachment는 한 줄이 아니라 `영역`입니다.
- 따라서 detachment는 아래 두 경계가 필요합니다.

1. `DET top`: 검은 cavity의 윗경계
2. `DET bottom`: 검은 cavity의 아랫경계

측정값은:

`detachment_thickness = DET bottom - DET top`

## 정상 이미지와 detach 이미지의 처리 차이

### 정상 이미지

정상 이미지에서는 detachment가 없다고 판단합니다.

예시:

- [21_OS_4H.tif](/D:/workspace/sumin/data/mouse_data_org/21_OS_4H.tif)

정상 이미지에서는 다음만 측정합니다.

- `Total retinal thickness = BM - TOP`
- `Outer retina thickness = BM - ONL`

### detach 이미지

detach 이미지에서는 detachment를 별도 layer로 취급합니다.

예시:

- [21_OS_6H.tif](/D:/workspace/sumin/data/mouse_data_org/21_OS_6H.tif)

detach 이미지에서는 다음을 각각 측정합니다.

- `Total retinal thickness = BM - TOP`
- `Outer retina thickness = BM - ONL`
- `Detachment thickness = DET bottom - DET top`

## 중심(center) 기준

중심은 **오른쪽 B-scan 이미지의 가로 중앙**을 기준으로 합니다.

즉:

- `bscan_left_x`, `bscan_right_x`를 찾고
- `center_x = (bscan_left_x + bscan_right_x) / 2`

로 정의합니다.

검증용 이미지에서는 이 중심선을 세로선으로 같이 그립니다.

## 중심 기준 좌우 처리 원칙

경계 추적과 측정은 **중심 기준으로 좌우를 독립적으로 처리**해야 합니다.

이 원칙은 매우 중요합니다.

- 좌측에서 찾은 경계를 우측으로 억지로 이어서 안 됩니다.
- 우측에서 찾은 경계를 좌측으로 억지로 끌어와서도 안 됩니다.
- 중심 근처에 식별 불가 구간이 있으면 그 구간은 `gap`으로 남겨야 합니다.

즉,

- `left segment`
- `right segment`

를 따로 관리하고,

- 서로 연결 가능한 근거가 없으면 연결하지 않습니다.

## 식별 불가 구간 처리 규칙

중앙이나 시신경유두 주변에는 경계가 흐려지거나 끊기는 경우가 있습니다.

이때 규칙은 다음과 같습니다.

1. 경계가 실제로 식별되지 않는 구간은 그리지 않는다.
2. annotation에서도 비워 둔 구간은 억지로 메우지 않는다.
3. 좌우 경계가 각각 존재하더라도, 가운데가 unreadable이면 gap으로 남긴다.

즉, "부드럽게 보이기 위해 연결"하는 것이 아니라,
"실제로 식별 가능한 구간만 표시"하는 것이 원칙입니다.

## 측정 가능 구간 규칙

실제 두께 측정은 **세 경계가 모두 존재하는 x 위치에서만** 수행합니다.

필수 경계:

- `TOP`
- `ONL`
- `BM`

따라서 아래 중 하나라도 없으면 그 x 위치는 측정하지 않습니다.

- TOP 없음
- ONL 없음
- BM 없음

즉:

`TOP, ONL, BM 셋 다 있을 때만 Total / Outer 측정`

입니다.

detach 이미지에서는 추가로:

- `DET top`
- `DET bottom`

이 둘이 모두 있을 때만 detachment thickness를 계산합니다.

## annotation 파일의 역할

annotation 파일은 "정답 좌표를 그대로 복사하는 파일"이 아니라,
"어떤 경계를 어떤 의미로 봐야 하는지"를 알려주는 GT 예시입니다.

예시:

- [21_OS_4H_annotation.tiff](/D:/workspace/sumin/data/mouse_data_org/annotation/21_OS_4H_annotation.tiff)
- [21_OS_6H_annotation.tiff](/D:/workspace/sumin/data/mouse_data_org/annotation/21_OS_6H_annotation.tiff)

annotation을 사용할 때 원칙:

1. annotation은 경계 의미를 알려주는 seed / prior로 사용한다.
2. 실제 다른 이미지에는 같은 정의를 raw OCT에서 다시 찾아야 한다.
3. 특정 x 숫자를 하드코딩해서 맞추는 방식은 지양한다.

## 경계 추적 전략

현재 프로젝트에서 지향하는 경계 추적 방식은 다음과 같습니다.

1. annotation 또는 초기 탐지 결과로 seed boundary를 만든다.
2. raw OCT intensity / local density / gradient를 사용해 실제 edge를 다시 찾는다.
3. 중심 기준 좌우를 독립적으로 탐색한다.
4. confidence가 유지되는 동안만 중심 방향으로 확장한다.
5. confidence가 무너지면 그 지점에서 멈추고 gap으로 남긴다.

즉,

- `정의`
- `raw intensity`
- `confidence`
- `center-based split`

가 핵심입니다.

## scale bar 사용 규칙

스케일은 TIFF 안의 scale bar를 우선 사용합니다.

우선순위:

1. 상하/좌우 scale bar가 둘 다 있으면 둘 다 사용
2. 상하 scale bar만 있어도 사용
3. 둘 다 실패하면 폴더 전체에서 가장 많이 검출된 `um/px`를 fallback default로 사용

즉, micron 변환은 가능한 한 이미지 안의 scale bar를 직접 기준으로 삼습니다.

## 출력 이미지 규칙

검증용 이미지에서 경계선은 다음을 따릅니다.

- 가능한 한 `1px` 두께
- 실제 B-scan 영역 안에서만 그림
- 중심선 같이 표시
- 식별 불가 gap은 유지

권장 색상:

- `TOP`: green
- `ONL`: cyan
- `BM`: magenta or yellow 계열 중 프로젝트 규칙에 맞는 하나
- `DET top / bottom`: black 또는 별도 구분 가능한 색

주의:

- 정상 이미지(예: 4H)에는 `BM / ONL / TOP` 세 줄만 있어야 합니다.
- detachment가 없는 이미지에 detachment 경계가 그려지면 안 됩니다.

## 4H와 6H의 GT 의미

### 21_OS_4H

- 정상 이미지
- detachment 없음
- GT는 `BM / ONL / TOP` 세 경계만 사용

### 21_OS_6H

- detachment 이미지
- GT는 `BM / ONL / TOP` + `DET top / DET bottom`

## 엑셀 결과에 포함되어야 하는 핵심 값

### 공통

- `x`
- `relative_x_px`
- `relative_deg` 또는 중심 기준 상대 위치
- `TOP y`
- `ONL y`
- `BM y`
- `Total thickness`
- `Outer thickness`
- 중심 관련 메타데이터

### detach 이미지 추가

- `DET top y`
- `DET bottom y`
- `Detachment thickness`
- `image_has_detachment`

## 배치 처리 원칙

나머지 이미지들에도 아래 규칙을 동일하게 적용해야 합니다.

1. 중심 기준 좌우를 독립적으로 본다.
2. BM / ONL / TOP 정의는 바꾸지 않는다.
3. 식별 불가 구간은 연결하지 않는다.
4. 세 경계가 모두 있는 위치에서만 측정한다.
5. detachment는 ONL-BM 사이의 검은 cavity로만 판단한다.
6. annotation에 맞춘 임시 수동 숫자 튜닝은 최종 규칙이 아니다.

즉, 4H/6H는 GT 예시이고, 실제 목표는 이 규칙이 폴더 전체에 일반화되는 것입니다.

## 현재 문서를 읽을 때 주의할 점

이 문서는 "최종 요구사항과 정의"를 기준으로 정리한 사양 문서입니다.  
즉, 코드가 이 문서와 100% 일치하지 않는 순간이 있더라도, 이 문서의 정의가 우선입니다.

특히 다음은 항상 고정입니다.

- BM 정의
- ONL 정의
- TOP 정의
- DET는 cavity top/bottom 두 경계
- 중심 기준 좌우 독립 처리
- 식별 불가 구간은 gap 유지
- 세 경계가 모두 있어야 측정

## 관련 파일

- 문서: [README_ANALYSIS_OCT.md](/D:/workspace/sumin/README_ANALYSIS_OCT.md)
- 단일 이미지 분석: [analysis_oct_03.py](/D:/workspace/sumin/src/analysis_oct_03.py)
- GT/배치 처리: [batch_gt_guided_processing.py](/D:/workspace/sumin/src/batch_gt_guided_processing.py)
- 출력 폴더: [output](/D:/workspace/sumin/data/mouse_data_org/output)
