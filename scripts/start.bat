@echo off
rem yomiageBotEx �N���X�N���v�g (Windows)

echo yomiageBotEx �N����...

rem uv���C���X�g�[������Ă��邩�`�F�b�N
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo uv���C���X�g�[������Ă��܂���B
    echo �C���X�g�[�����@: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    pause
    exit /b 1
)

rem .env�t�@�C���̑��݃`�F�b�N
if not exist ".env" (
    echo .env�t�@�C����������܂���B
    echo DISCORD_TOKEN=your_token_here ���L�q���� .env �t�@�C�����쐬���Ă��������B
    pause
    exit /b 1
)

rem �ˑ��֌W�̃C���X�g�[��
echo �ˑ��֌W���C���X�g�[����...
uv sync --no-install-project

rem �{�b�g�̋N��
echo �{�b�g���N�����܂�...
uv run --no-project python bot.py

pause