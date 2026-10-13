# RecordClass — 강의 녹음 STT 도구

[mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)로 60~90분 분량의 강의 녹음을
텍스트(TXT/SRT/VTT/Markdown)로 변환하는 **macOS(Apple Silicon) 전용** 데스크톱 GUI 도구입니다.

- 모든 처리는 로컬에서 수행 — 녹음 파일이 외부로 전송되지 않습니다
- 여러 파일을 대기 큐에 넣고 순서대로 일괄 전사
- 진행률·실시간 자막 미리보기, 언제든 취소 가능
- (선택) 로컬 LLM으로 전사 원문 교정, 완료된 강의는 요약 노트 생성

## 요구 사항

- Apple Silicon Mac (M1 이상) — Intel Mac, Windows, Linux는 지원하지 않습니다
- Python 3.11 이상
- `ffmpeg` (`brew install ffmpeg`)

## 설치 및 실행

```bash
git clone https://github.com/sunwoo07/RecordClass.git
cd RecordClass
```

### 방법 A: uv 사용 (권장)

```bash
brew install uv
uv sync
uv run python -m sttgui.main
```

### 방법 B: pip 사용 (uv 없이)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m sttgui.main
```

다음부터는 `source .venv/bin/activate && python -m sttgui.main`만 실행하면 됩니다.

## 사용법

1. 강의 녹음 파일을 창에 끌어다 놓거나 왼쪽 위 **＋**(⌘O)로 선택 (여러 개 가능)
   - 지원 형식: mp3, wav, m4a, mp4, aac, flac, ogg, mov 등
   - 왼쪽 대기열에 파일마다 상태(대기·진행·완료·실패)와 진행률이 표시됩니다
2. 설정 변경이 필요하면 위쪽의 **설정** 탭(⌘,)을 엽니다. 왼쪽 아래 설정 요약을 눌러도 됩니다
   - 모델 / 언어(한국어·영어·자동 감지) / 전문 용어 힌트
   - 인식 품질: 이전 문맥 참조 끄기 / 반복 문장 제거 / 무음 구간 환각 건너뛰기 (기본 모두 켜짐),
     음성 전처리(ffmpeg 잡음 제거·음량 정규화, 기본 꺼짐)
   - 저장: 파일 형식(TXT, SRT, VTT, Markdown) / 저장 위치(기본값: 프로젝트의 `output/` 폴더)
   - 바꾸는 즉시 저장되어 다음 실행 때도 유지되며, 전사 도중 바꾼 설정은 다음 파일부터 적용됩니다
3. **전사 시작** 클릭 — 대기열의 파일이 순서대로 처리되고, 작업 탭에 내용이 실시간으로 나타납니다
4. 대기열에서 완료된 파일을 고르면 정리된 전사본을 바로 읽을 수 있고, **Finder에서 보기**로 결과 파일을 엽니다
5. (선택) **요약 만들기** — `<파일명>.summary.md`로 강의 노트를 저장하고, **요약** 보기로 앱 안에서 읽습니다

## LLM 교정·요약 (선택)

설정 탭의 **LLM 후처리 → 전사 후 원문 교정**을 켜면, 전사가 끝난 뒤 로컬 LLM
([mlx-lm](https://github.com/ml-explore/mlx-lm), 기본 모델 `mlx-community/Qwen3.5-9B-MLX-4bit`)이
잘못 인식된 단어·맞춤법·띄어쓰기를 고칩니다.

- 원본 결과는 그대로 두고 `<파일명>.corrected.txt` 등 교정본을 따로 저장합니다 (타임스탬프 유지)
- 설정의 "전문 용어 힌트"가 교정에도 용어집으로 쓰입니다
- 요약은 교정본이 있으면 교정본을, 없으면 원본 결과를 사용합니다
- 첫 사용 시 모델을 내려받습니다(약 6GB). 16GB 메모리 Mac 기준으로 맞춘 모델이며,
  강의 1시간당 교정에 수 분~10여 분이 더 걸립니다
- 다른 mlx-lm 모델 이름을 직접 입력해 바꿀 수 있습니다

동작을 먼저 확인하고 싶다면 `samples/lecture_sample.mp3`로 테스트해 보세요.

> 첫 실행 시 선택한 모델을 Hugging Face에서 자동 다운로드합니다(수백 MB~3GB).
> 인터넷 연결이 필요하며, 이후에는 로컬 캐시(`~/.cache/huggingface`)를 사용합니다.

## 모델 선택 기준

| 모델 | 특징 |
|------|------|
| **large-v3-turbo** (기본값) | 속도와 정확도의 균형이 가장 좋음, 강의 녹음에 권장 |
| large-v3 | 정확도가 가장 높지만 처리 시간이 김 |
| medium / small | 더 빠르지만 정확도는 낮음 (소음이 적고 발음이 명확한 경우) |

60~90분 녹음 기준, M1/M2에서 large-v3-turbo는 대략 실제 길이의 10~20% 시간이 걸립니다(하드웨어에 따라 다름).

## 문제 해결

- **`ffmpeg` 관련 오류** → `brew install ffmpeg` 후 터미널을 다시 열어 실행
- **`mlx` 설치 실패** → Apple Silicon용 네이티브 Python인지 확인: `python3 -c "import platform; print(platform.machine())"` 결과가 `arm64`여야 합니다

## 테스트

```bash
python -m unittest        # uv 사용 시: uv run python -m unittest
```

샘플 녹음을 실제로 전사하는 테스트(`tests/test_e2e.py`)는 small 모델(`mlx-community/whisper-small-mlx`)이 캐시에 있을 때만 실행되고, 없으면 건너뜁니다.
