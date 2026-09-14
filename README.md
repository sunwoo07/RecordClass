# RecordClass — 강의 녹음 STT 도구

`mlx-whisper`를 이용해 60~90분 분량의 강의 녹음을 텍스트로 변환하는 macOS(Apple Silicon) 전용 데스크톱 GUI 도구입니다.

PySide6로 만든 네이티브 GUI이며, 실제 전사 작업은 별도 프로세스에서 실행되어 진행률을
실시간 스트리밍하고 언제든 취소할 수 있습니다.

## 요구 사항

- Apple Silicon Mac (M1 이상)
- macOS + Homebrew의 `ffmpeg` (`brew install ffmpeg`)
- [uv](https://docs.astral.sh/uv/) (`brew install uv`)

## 설치

```bash
uv sync
```

## 실행

```bash
uv run python -m sttgui.main
```

## 사용법

1. 강의 녹음 파일을 드래그하거나 "찾아보기"로 선택 (mp3, wav, m4a, mp4, aac, flac, ogg, mov 등 지원)
2. 모델/언어/출력 형식(TXT, SRT, VTT)을 선택
3. 저장 위치를 지정 (기본값: 원본 파일과 같은 폴더)
4. "전사 시작" 클릭 — 진행률과 실시간 자막 미리보기가 표시됨
5. 완료 후 "결과 폴더 열기"로 바로 확인

첫 실행 시 선택한 모델을 Hugging Face에서 자동 다운로드하므로 인터넷 연결과
약간의 시간이 필요합니다(이후에는 로컬 캐시 사용).

## 모델 선택 기준

- **large-v3-turbo (기본값)**: 속도와 정확도의 균형이 가장 좋음, 강의 녹음에 권장
- **large-v3**: 정확도가 가장 높지만 처리 시간이 김
- **medium / small**: 더 빠르지만 정확도는 낮아짐 (배경 소음이 적고 발음이 명확한 경우 적합)

60~90분 분량 기준, M1/M2 계열에서 large-v3-turbo는 대략 실제 길이의 10~20% 수준의
시간이 소요됩니다(하드웨어에 따라 다름).
