# RecordClass — 강의 녹음 STT 도구

[mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)로 60~90분 분량의 강의 녹음을
텍스트(TXT/SRT/VTT/Markdown)로 변환하는 **macOS(Apple Silicon) 전용** 데스크톱 GUI 도구입니다.

- 모든 처리는 로컬에서 수행 — 녹음 파일이 외부로 전송되지 않습니다
- 여러 파일을 대기 큐에 넣고 순서대로 일괄 전사
- 진행률·실시간 자막 미리보기, 언제든 취소 가능

## 요구 사항

- Apple Silicon Mac (M1 이상) — Intel Mac, Windows, Linux는 지원하지 않습니다
- Python 3.10 이상
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

1. 강의 녹음 파일을 창에 드래그하거나 "파일 추가"로 선택 (여러 개 가능)
   - 지원 형식: mp3, wav, m4a, mp4, aac, flac, ogg, mov 등
2. 설정 변경이 필요하면 **환경설정(⌘,)** 을 엽니다 — 모델 / 언어(한국어·영어·자동 감지) /
   출력 형식(TXT, SRT, VTT, Markdown) / 저장 위치(기본값: 프로젝트의 `output/` 폴더)
   - 설정은 자동 저장되어 다음 실행 때도 유지되며, 현재 설정은 메인 창에 한 줄로 표시됩니다
   - 전사 도중 바꾼 설정은 다음 파일부터 적용됩니다
3. "전사 시작" 클릭 — 큐의 파일이 순서대로 처리됩니다
4. 완료 후 "결과 폴더 열기"로 확인

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
