<div align="center">

# 🎙️ RecordClass

**강의 안 듣고 딴짓해도 OK — 마치 강의를 들은 듯한 행복한 강의생활**

60~90분 강의 녹음을 받아쓰기하고, 교정하고, 요약 노트까지.<br>
**전부 내 Mac 안에서만** 처리하고, **내 강의에 맞게 직접 조정할 수 있는** 데스크톱 STT 도구입니다.

![macOS](https://img.shields.io/badge/macOS-Apple%20Silicon-000000?logo=apple&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![MLX](https://img.shields.io/badge/MLX-whisper%20%2B%20LM-FF6F00)
![100% Local](https://img.shields.io/badge/100%25-Local-2EA043)
![No API Key](https://img.shields.io/badge/API%20Key-필요%20없음-2EA043)

</div>

---

## ✨ 왜 RecordClass인가

### 🔒 100% 로컬 — 녹음도, LLM도 내 Mac 밖으로 나가지 않습니다

STT(mlx-whisper)뿐 아니라 **교정·요약 LLM(mlx-lm)까지 전부 Apple Silicon에서 로컬로 실행**합니다.

- 녹음 파일과 전사본이 **어떤 서버로도 업로드되지 않습니다**
- OpenAI·Claude 같은 **클라우드 API 키가 필요 없고**, 사용량 과금이나 월 구독도 없습니다
- 모델을 한 번 내려받은 뒤에는 **인터넷 없이도** 전사·교정·요약이 모두 됩니다
- 녹음 공유가 조심스러운 강의, 사내 교육, 세미나도 안심하고 처리할 수 있습니다

### 🎛️ 내 강의에 맞게 커스터마이징

정해진 결과만 받아야 하는 일반 STT 서비스와 달리, 인식부터 출력까지 거의 모든 단계를 직접 고를 수 있습니다.

| 단계 | 바꿀 수 있는 것 |
|------|----------------|
| **모델** | Whisper 모델(large-v3-turbo / large-v3 / medium / small), 교정·요약 LLM은 **mlx-lm 모델 이름을 직접 입력해 교체** |
| **인식** | 언어(한국어·영어·자동 감지), **전문 용어 힌트**(과목 용어집처럼 쓰이고 LLM 교정에도 반영) |
| **품질** | 이전 문맥 참조 끄기, 반복 문장 제거, 무음 구간 환각 건너뛰기, ffmpeg 잡음 제거·음량 정규화 |
| **출력** | TXT / SRT / VTT / Markdown 선택, 문단 나누는 무음 간격, TXT 타임스탬프 표시, 저장 위치 |
| **후처리** | LLM 원문 교정 켜기/끄기, 강의 요약 노트 생성 |

모든 설정은 바꾸는 즉시 저장되고, 코드가 열려 있으니 프롬프트나 후처리 규칙까지 원하는 대로 고칠 수 있습니다.

### 📚 그 밖의 기능

- 여러 파일을 대기열에 넣고 순서대로 **일괄 전사**
- 진행률과 **실시간 자막 미리보기**, 언제든 취소
- 결과물을 **앱 안에서 바로 읽기** (전사본·요약), Finder에서 열기
- 라이트/다크 모드를 따르는 macOS 스타일 UI

---

## 🔄 동작 흐름

```
🎧 강의 녹음 ──▶ (선택) ffmpeg 전처리 ──▶ mlx-whisper 전사 ──▶ 중복 제거·문단 정리
                                                              │
                         📄 TXT · SRT · VTT · MD ◀────────────┤
                                                              ▼
                         ✍️ .corrected.*  ◀── (선택) mlx-lm 교정
                                                              │
                         📝 .summary.md   ◀── (선택) mlx-lm 요약
```

모든 화살표가 **로컬에서** 일어납니다.

---

## 📦 요구 사항

- Apple Silicon Mac (M1 이상) — Intel Mac, Windows, Linux는 지원하지 않습니다
- Python 3.11 이상
- `ffmpeg` (`brew install ffmpeg`)

## 🚀 설치 및 실행

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

> 💡 첫 실행 시 선택한 모델을 Hugging Face에서 자동으로 내려받습니다(Whisper 수백 MB~3GB, LLM 약 6GB).
> 이때만 인터넷이 필요하고, 이후에는 로컬 캐시(`~/.cache/huggingface`)를 사용합니다.

동작을 먼저 확인하고 싶다면 `samples/lecture_sample.mp3`로 테스트해 보세요.

---

## 🧭 사용법

1. 강의 녹음 파일을 창에 끌어다 놓거나 왼쪽 위 **＋**(⌘O)로 선택 (여러 개 가능)
   - 지원 형식: mp3, wav, m4a, mp4, aac, flac, ogg, mov 등
   - 왼쪽 대기열에 파일마다 상태(대기·진행·완료·실패)와 진행률이 표시됩니다
2. 설정 변경이 필요하면 위쪽의 **설정** 탭(⌘,)을 엽니다. 왼쪽 아래 설정 요약을 눌러도 됩니다
   - 바꾸는 즉시 저장되어 다음 실행 때도 유지되며, 전사 도중 바꾼 설정은 다음 파일부터 적용됩니다
   - 기본 저장 위치는 프로젝트의 `output/` 폴더입니다
3. **전사 시작** 클릭 — 대기열의 파일이 순서대로 처리되고, 작업 탭에 내용이 실시간으로 나타납니다
4. 대기열에서 완료된 파일을 고르면 정리된 전사본을 바로 읽을 수 있고, **Finder에서 보기**로 결과 파일을 엽니다
5. (선택) **요약 만들기** — `<파일명>.summary.md`로 강의 노트를 저장하고, **요약** 보기로 앱 안에서 읽습니다

## 🤖 로컬 LLM 교정·요약 (선택)

설정 탭의 **LLM 후처리 → 전사 후 원문 교정**을 켜면, 전사가 끝난 뒤 로컬 LLM
([mlx-lm](https://github.com/ml-explore/mlx-lm), 기본 모델 `mlx-community/Qwen3.5-9B-MLX-4bit`)이
잘못 인식된 단어·맞춤법·띄어쓰기를 고칩니다.

- 원본 결과는 그대로 두고 `<파일명>.corrected.txt` 등 교정본을 따로 저장합니다 (타임스탬프 유지)
- 설정의 "전문 용어 힌트"가 교정에도 용어집으로 쓰입니다
- 요약은 교정본이 있으면 교정본을, 없으면 원본 결과를 사용합니다
- 16GB 메모리 Mac 기준으로 맞춘 기본 모델이며, 강의 1시간당 교정에 수 분~10여 분이 더 걸립니다
- 메모리가 넉넉하면 더 큰 모델, 부족하면 더 작은 모델로 — **다른 mlx-lm 모델 이름을 직접 입력해 바꿀 수 있습니다**

## 🎯 모델 선택 기준

| 모델 | 특징 |
|------|------|
| **large-v3-turbo** (기본값) | 속도와 정확도의 균형이 가장 좋음, 강의 녹음에 권장 |
| large-v3 | 정확도가 가장 높지만 처리 시간이 김 |
| medium / small | 더 빠르지만 정확도는 낮음 (소음이 적고 발음이 명확한 경우) |

60~90분 녹음 기준, M1/M2에서 large-v3-turbo는 대략 실제 길이의 10~20% 시간이 걸립니다(하드웨어에 따라 다름).

---

## 🛠️ 문제 해결

- **`ffmpeg` 관련 오류** → `brew install ffmpeg` 후 터미널을 다시 열어 실행
- **`mlx` 설치 실패** → Apple Silicon용 네이티브 Python인지 확인: `python3 -c "import platform; print(platform.machine())"` 결과가 `arm64`여야 합니다

## 🧪 테스트

```bash
python -m unittest        # uv 사용 시: uv run python -m unittest
```

샘플 녹음을 실제로 전사하는 테스트(`tests/test_e2e.py`)는 small 모델(`mlx-community/whisper-small-mlx`)이 캐시에 있을 때만 실행되고, 없으면 건너뜁니다.
