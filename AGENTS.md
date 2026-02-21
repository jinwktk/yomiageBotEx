# 作業メモ

## 2025-10-23
- `/replay` で生成した音声ファイルがプロジェクト外に保存される問題を再現するため、テスト `tests/test_replay_file_storage.py` を追加。
- `tests/conftest.py` を作成し、Pytest 実行時にプロジェクトルートを `sys.path` に追加する共通処理を定義。
- `cogs/recording.py` のリプレイ保存先を `cogs` ディレクトリ基準ではなくプロジェクトルート直下の `recordings/replay` に固定し、`except` ブロックのインデント崩れを修正。
- `pytest` を実行し、既存テスト・新規テストが全て成功することを確認。
- 生成された `recording_user372768430149074954_30.0s_20251023_220525.wav` を解析。長さは 4.24 秒、主要周波数が 30〜50Hz 帯域に集中しており、期待したユーザー音声が入っていない可能性を確認。
- `data/audio_buffers.json` に保存される WaveSink 出力がヘッダのみで PCM データを持たない場合がある点を確認。今後、WaveSink のフォーマット処理かノーマライズ手順の見直しが必要。
- `utils/real_audio_recorder.py` を修正し、連続バッファの時間範囲算出を実データ長ベースに変更。チェックポイント再開時に `recording_status` を更新するようにして、1回目の `/replay` 以降でもチャンクが蓄積され続けるよう対応。
- `tests/test_real_audio_recorder_buffers.py` を追加し、連続バッファの時間管理ロジックをユニットテストで回帰確認。
- `utils/hot_reload.py` を新設し、Cogファイルの更新を検知できるホットリロードマネージャを実装。`bot.py` にウォッチタスクを組み込み、`config.yaml` の `development.hot_reload` で有効化できるようにした。
- `tests/test_hot_reload_manager.py` を追加し、ファイル更新検知と欠損時の復帰をテスト。

## リポジトリ構成メモ（変更差分）
- `cogs/recording.py`: リプレイ保存ディレクトリの解決方法を修正、例外処理のインデントを修正。
- `tests/conftest.py`: 新規。Pytest の共通セットアップ用。
- `tests/test_replay_file_storage.py`: 新規テスト。保存先ディレクトリの回帰チェック。

## 実行コマンド
- `pytest`

## 2025-10-24
- 手動録音コマンド実装に向けた TDD ステップとして `tests/test_manual_recording_manager.py` を追加し、先にフェイルさせて仕様を固めた。
- `utils/manual_recording_manager.py` を新設し、`RecordingCog` に `/start_record`・`/stop_record` を追加。手動録音中はリアルタイム録音を一時停止し、停止時に混合WAVとユーザー別ZIPを生成するよう調整。`tests/test_recording_cog_manual_commands.py` でコマンド挙動を検証し、既存テストと合わせて `pytest` が全件成功することを確認。
- 音声が「あいうあいう」のように二重化する報告を受け、連続バッファへの重複追加が原因かを切り分けるため `tests/test_real_audio_recorder_buffers.py` にチェックポイントとコールバックの二重投入シナリオを再現する非同期テストを追加。
- `_add_to_continuous_buffer` にハッシュベースの重複チャンク検出を実装し、チェックポイント直後の `WaveSink` コールバックで同一音声が再登録されないよう `utils/real_audio_recorder.py` を更新。重複キャッシュは最新チャンクのみ保持し、時間差0.2秒以内かつデータ一致時にスキップする方式とした。
- `pytest` を再実行し、20件すべてのテストが成功することを確認。

## 2025-10-25
- 読み上げ実行時にボットが離脱するとの報告を受け、`MessageReaderCog._attempt_auto_reconnect` が再接続先を見つけられない場合でも既存クライアントを強制切断してしまう挙動を再現するテスト `tests/test_message_reader_reconnect.py` を追加。
- `_attempt_auto_reconnect` を修正し、有人ボイスチャンネルが見つかった場合のみ既存接続をクリーンアップするよう変更。すでにターゲットチャンネルへ接続済みの場合は再利用するフェイルセーフを追加。
- `pytest` を実行し、21件すべてのテストが成功することを確認。
- `py-cord` を PR #2651 (commit 59d4860) のブランチへ切り替え。`python3 -m pip install --break-system-packages git+https://github.com/Pycord-Development/pycord.git@refs/pull/2651/head` を実行し、`pyproject.toml` の依存も VCS 参照へ更新。
- Pycord PR環境への移行後に挨拶が鳴らなくなった件を調査し、`TTSCog.on_voice_state_update` に `@commands.Cog.listener()` を付与するテスト (`tests/test_tts_cog_listeners.py`) を追加。イベントリスナー登録を明示して挨拶再生が復活することを確認。
- 自動再接続中にハンドシェイクが完了するケースで既存VCを切断しないよう `_attempt_auto_reconnect` を調整。ハンドシェイク待ちを再現する `tests/test_message_reader_reconnect.py::test_attempt_auto_reconnect_waits_for_handshake` を追加し、23件の `pytest` が成功することを確認。

## 2025-11-12
- 辞書登録が稼働中に即時反映されない問題を再現するため、Bot内で辞書マネージャが共有されていることを検証する `tests/test_dictionary_realtime_updates.py` をTDDで追加。
- `cogs/message_reader.py` と `cogs/dictionary.py` に共通の `_resolve_dictionary_manager` を実装し、`bot.dictionary_manager` を通じて単一インスタンスを共有するよう修正。`bot.py` 側でも `YomiageBot` 初期化時に `DictionaryManager` を生成しておくことでCog読み込み順に依存しないようにした。
- `README.md` に「辞書更新は即時適用」機能を追記し、ユーザー向けに改善点を明記。
- `pytest` を実行し、24件すべて成功することを確認。
- 変更ファイル: `tests/test_dictionary_realtime_updates.py` (新規), `cogs/message_reader.py`, `cogs/dictionary.py`, `bot.py`, `README.md`。
- 挨拶メッセージに辞書が適用されない不具合を再現する `tests/test_tts_greeting_dictionary.py` を追加し、`cogs/tts.py` に辞書マネージャ共有ロジックと挨拶テキストへの適用処理を実装。`README.md` へ挨拶にも辞書が反映される旨を追記し、`pytest`（25件）で回帰確認。

## 2025-11-16
- ボイス心拍が10秒以上ブロックされる原因となっていた `voice_client.stop_recording()` の同期ブロックを再現するため、`tests/test_real_audio_recorder_async.py` を追加し、録音停止/開始処理がメインスレッド以外で実行されることをTDDで確認。
- `utils/real_audio_recorder.py` に `_stop_recording_non_blocking` / `_start_recording_non_blocking` を実装し、録音開始・停止・定期チェックポイント・強制チェックポイントの各処理から呼び出すようにしてイベントループを塞がない構造へ変更。
- `README.md` に録音チェックポイントの非ブロッキング化を追記し、改善点をユーザー向けに共有。
- `pytest` を実行し、27件のテストが全て成功することを確認。
- Opusデコードエラーのログが「SSRC=xxxx」だけで原因が追えなかった問題を改善し、`bot.py` のパッチでギルド/チャンネル/ユーザー名付きの文面に変更。READMEにも監視改善点を追記し、27件の `pytest` 成功を確認。
- `MessageReaderCog._attempt_auto_reconnect` のハンドシェイク待機を最大8秒まで延長する `_wait_for_existing_client` を実装し、既存VCが接続完了する前に切断されていたログ(Valworld)を再現テスト `tests/test_message_reader_reconnect.py` で検証。READMEに自動再接続の待機仕様を追記し、`pytest` 27件成功を確認。

## 2025-11-19
- 読み上げだけを行う `/echo` コマンドを追加するため、`tests/test_message_reader_echo_command.py` を先に作成してTDDで仕様化。辞書適用・音声生成・エフェメラル応答の挙動を検証。
- `cogs/message_reader.py` に `/echo` 実装を追加し、VC非接続時は自動再接続を試みつつ、成功時のみ TTS を生成して `play_audio_from_bytes` を呼び出す構造にした。読み上げ結果はVCのみで流し、テキストチャンネルには残らないようエフェメラルレスポンスに統一。
- READMEのコマンド一覧に `/echo` を追記し、機能概要を共有。
- `pytest` を実行し、28件のテスト（新規含む）が全て成功することを確認。
- Discord側の切断でボットがVCを抜けたままになるケースを解消するため、`MessageReaderCog` に最終接続チャンネルを記録する仕組みと `sessions.json` フォールバックを追加。ユーザー検出に失敗しても最後のチャンネルへ再接続できるよう `_find_fallback_channel` を実装し、`tests/test_message_reader_reconnect.py` にフォールバック用テストを追加。READMEへ自動復帰仕様を追記し、`pytest` 29件成功を確認。
- VC受信スレッドが `nacl.exceptions.CryptoError` でクラッシュしていたため、`bot.py` で `discord.voice_client.VoiceClient.unpack_audio` をラップし、復号失敗フレームをスキップしてギルド/チャンネル名付きで警告ログを出すようパッチ。READMEに暗号化エラー耐性を追記し、`pytest` 29件成功を確認。
- ログファイル圧縮時にメインスレッドがブロックされて心拍が止まる問題に対応するため、`utils/logger.py` の `CompressedRotatingFileHandler` を非同期圧縮化し、gzip処理をデーモンスレッドで実行するよう変更。READMEへイベントループ非ブロッキング化を追記し、`pytest` 29件成功を確認。
- 読み上げリクエストがVC未接続時にスキップされるのを防ぐため、`MessageReaderCog` にギルド単位のメッセージキューと非同期ワーカーを実装。再接続後に順次処理する `_enqueue_message` / `_process_queue` を追加し、`tests/test_message_reader_queue.py` でTDD確認。READMEへ「読み上げはキュー処理で順番通り再生される」旨を追記し、`pytest` 30件成功を確認。

## 2025-11-23
- `/echo`コマンドのエフェメラル返信文言を「音声を流しました」に統一するため、`tests/test_message_reader_echo_command.py` の期待を先に更新し、対象テストが失敗することを確認。
- `cogs/message_reader.py` の `/echo` 実装で `ctx.respond` の内容を「音声を流しました」に変更し、実装を仕様に合わせた。
- READMEのコマンド一覧で `/echo` の説明に「返信は『音声を流しました』固定」と追記してユーザー向けに仕様を明記。
- `python3 -m pytest` を実行し、30件すべてのテストが成功することを確認。

## 2025-11-29
- ユーザー参加時に古い `guild.voice_client` が残っていると再参加せず録音・挨拶が起動しない問題を再現するため、`tests/test_voice_auto_join.py` を新設し、切断済みボイスクライアントが存在するケースで `connect_to_voice` が呼ばれることを期待するテストを追加（先に失敗を確認）。
- `cogs/voice.py` の `handle_user_join` を改修し、`voice_client.is_connected()` が `False` の場合は stale 接続として切断・再参加するよう分岐を整理。録音開始時の参照もローカル変数 `voice_client` に統一。
- READMEのチャット読み上げ機能一覧に「古いボイス接続参照があってもユーザー参加で自動復帰」項目を追記。
- `python3 -m pytest` を実行し、31件のテスト（新規含む）が全て成功することを確認。

## 2025-12-04
- VC無人時の誤読上げを防ぐため、`tests/test_message_reader_queue.py` に「参加者ゼロなら読み上げキューに積まない」テストを、`tests/test_message_reader_echo_command.py` に「/echoは無人VCでエラー応答」テストを追加してTDD開始。
- `cogs/message_reader.py` に ` _has_non_bot_listeners` を実装し、`on_message`・`_play_job`・`/echo` でBot以外の参加者がいない場合は読み上げをスキップするよう制御を追加。
- READMEのコマンド一覧とチャット読み上げ機能にも「無人VCでは再生しない」仕様を追記。
- `python3 -m pytest`（33件）を実行し、新旧テストが全て成功したことを確認。

## 2026-01-02
- `logs/yomiage.log` でStyle-Bert-VITS2へのTTSリクエストが `max_text_length`（デフォルト100文字）を超過して422エラーになっていた点を確認。
- `tests/test_tts_text_limit.py` を追加し、`generate_speech` がキャッシュ参照前に渡すテキスト長が設定上限を超えないことを確認するTDDテストを作成。
- `utils/tts.py` の文字数制限処理を更新し、省略記号込みでも上限以内に収まるよう切り詰めつつ、上限より短い場合は省略記号を付けないフェイルセーフを追加。
- READMEのTTS機能一覧に文字数上限を安全に短縮して422エラーを防止する仕様を追記。
- `python3 -m pytest tests/test_tts_text_limit.py` を実行し、新規テストが成功することを確認。

## 2026-01-03
- ボイスチャンネルに非Bot参加者がいない場合はギルド単位で読み上げを自動一時停止し、参加者が戻ると自動再開する制御を `cogs/message_reader.py` に実装。`/reading` の設定値を変更せずに安全に自動停止できるようにした。
- 自動再接続時に目標チャンネルが無人であれば接続を行わないようにし、無人状態では `guild_auto_paused` フラグを立ててメッセージ読み上げを抑止するよう `_attempt_auto_reconnect` を改修。
- `tests/test_message_reader_reconnect.py` に自動一時停止の期待を確認するテスト、およびフォールバックチャンネルでの再接続テストを追加し、`tests/test_message_reader_queue.py` には無人検知で読み上げが止まり、参加者復帰で再開するシナリオを追加。
- READMEに「無人VCでは読み上げを自動停止する」仕様を追記し、AGENTS.mdにも作業内容を記録。
- `python3 -m pytest` を実行し、36件のテストが全て成功することを確認。

## 2026-01-11
- `/replay` で「@ソルト・ライオモッチ の過去30.0秒間の音声データが見つかりません」と表示された件を調査。`logs/yomiage.log`（タイムスタンプ 2026-01-11 07:57:39 付近）を確認し、`RealTimeRecorder` が同時刻にチェックポイントを作成しているが `sink.audio_data keys: []` と出力されており、WaveSinkから音声チャンクが戻っていない状態だったことを把握。
- 同ログで `continuous_buffers` 内のユーザーID一覧は取得できているものの、リクエストした30秒範囲内に重なるチャンクが1件も無いため `_extract_audio_range` が `No matching chunks` を返し、該当ユーザーのデータが見つからない挙動を確認。
- 07:53頃のログには該当ユーザーのチャンク追加 (`RealTimeRecorder: Added audio chunk ... user 1033950280871579648`) が記録されているが、07:57までに新しいチャンクが1件も記録されていないことから、ボイスチャネル側で有効な音声が4分以上発生していない（もしくはWaveSinkが受信できていない）場合に同エラーメッセージとなることを整理。
- `/replay` は ReplayBufferManager（録音リレー経由の新システム）を常に優先し、取得に成功した場合は旧リアルタイムバッファへフォールバックしないよう `recording.prefer_replay_buffer_manager` フラグを追加。挙動を検証する `tests/test_replay_buffer_integration.py` も作成してTDD実施。
- `RealTimeAudioRecorder` に `get_buffer_health_summary` を実装し、時間範囲にマッチするチャンクが無い場合は最後に記録された時刻をログへ出力。WaveSinkコールバックや `smooth_audio_relay` でも空データ時の警告ログを追加。
- `/replay_diag` コマンドを新設し、RealTimeAudioRecorder/RecordingCallbackManager 双方のチャンク有無と最終記録時刻をエフェメラルEmbedで提示できるようにした。`/replay` のエラー応答にも最後に記録された経過秒数を追記。
- `config.yaml` と README に `prefer_replay_buffer_manager` や `/replay_diag` の説明を追記し、診断フローを文書化。
- `python3 -m pytest` を実行し、既存36件＋新テストを含む37件すべてが成功することを確認。
- 録音の実音声確認用に `/replay_probe` を追加し、RecordingCallbackManager から最新チャンクをWAVで返す診断フローを実装。`tests/test_replay_probe_command.py` を追加してTDDで検証。
- 音声リレーが無音状態のまま継続する場合に自動でセッションを再起動する仕組みを `utils/smooth_audio_relay.py` に追加し、`tests/test_smooth_audio_relay_silence_restart.py` で挙動を確認。
- `config.yaml` に `audio_relay.silence_restart` を追加し、README に `/replay_probe` と無音時再起動の仕様を追記。
- `python3 -m pytest tests/test_replay_probe_command.py tests/test_smooth_audio_relay_silence_restart.py` を実行し、5件のテストがすべて成功することを確認。

## 2026-01-16
- `tests/test_message_reader_ignore_prefixes.py` を追加し、デフォルトの読み上げ除外プレフィックスで「`」「/」「;」始まりのメッセージがスキップされることをTDDで確認。
- `cogs/message_reader.py` のデフォルト `ignore_prefixes` に「`」「;」を追加し、`config.yaml` の設定例も更新。
- READMEの読み上げ機能説明と `TECHNICAL_SPECIFICATION.md` / `CLAUDE.md` の設定例を最新のプレフィックス一覧に合わせて更新。
- `python3 -m pytest tests/test_message_reader_ignore_prefixes.py` を実行し、3件のテストが成功することを確認。

## 2026-02-14
- 現在の未コミット差分を整理して、機能削除前のベースラインを先にコミットする方針を確定。
- 削除対象は `relay` 系と `admin` 系に限定し、`recording`（壊れている箇所は修正して継続利用）・`tts`・`user_settings`・`dictionary` は維持する方針で合意。
- コミット前のドキュメント更新ルールに合わせ、`README.md` と `AGENTS.md` を更新。
- `bot.py` の読み込みCogから `cogs.relay` / `cogs.admin` を除外し、音声受信判定を録音機能のみ参照する実装に整理。
- `config.yaml` から `audio_relay` 設定ブロックを削除し、設定項目を読み上げ・録音中心へ整理。
- `README.md` から音声リレー関連の説明と `/reload_cog` 記述を削除し、現行運用に合わせて更新。
- 以下の不要ファイルを削除:
  - `cogs/relay.py`
  - `cogs/admin.py`
  - `check_relay_status.py`
  - `utils/smooth_audio_relay.py`
  - `utils/audio_relay.py`
  - `utils/audio_relay_old.py`
  - `utils/simple_audio_relay_old.py`
  - `tests/test_smooth_audio_relay_silence_restart.py`
- `python3 -m pytest` を実行し、42件のテストが全て成功することを確認。
- 録音機能の不具合修正として `tests/test_real_audio_recorder_buffers.py` に RecordingCallbackManager 連携確認テストを追加し、チェックポイントと finished callback の重複経路でもチャンク転送が1回に抑制されることをTDDで固定。
- `tests/test_recording_cog_voice_state.py` を新規追加し、`RecordingCog.on_voice_state_update` で録音停止が await されることを検証。
- `utils/real_audio_recorder.py` に RecordingCallbackManager への直接転送処理を追加し、重複チャンク（同一シグネチャ・短時間）をスキップする保護を実装。
- `cogs/recording.py` の録音停止を `await self.real_time_recorder.stop_recording(...)` へ修正し、WaveSink 単体では使えないシミュレーション録音分岐を安全化。`/replay_probe` の案内文もリレー依存の表現から録音機能依存の表現へ更新。
- `python3 -m pytest tests/test_real_audio_recorder_buffers.py tests/test_recording_cog_voice_state.py` および `python3 -m pytest` を実行し、44件のテストが全て成功することを確認。
- ユーザー指定 `/replay` で機械音化する報告への対応として、`utils/replay_buffer_manager.py` の `_process_user_audio` を修正。チャンク結合時の「先頭44バイト固定スキップ」を廃止し、`wave` で各チャンクのPCMを抽出して連結する方式に変更。
- 同処理で `normalize=True` 時に16bit PCMピークを抑制する `_normalize_pcm_16bit` を追加し、`max_volume=0dB` 張り付きのクリップ歪みを軽減。
- 回帰テスト `tests/test_replay_buffer_manager_audio.py` を新規追加し、可変WAVヘッダ（JUNKチャンク付き）でも正しく結合できることと、正規化時にピーク抑制されることをTDDで確認。
- `python3 -m pytest tests/test_replay_buffer_manager_audio.py tests/test_replay_buffer_integration.py` と `python3 -m pytest` を実行し、46件のテストが全て成功することを確認。
- 「1回録音コマンド実行後に再度録音が自動再開せず、/replay で再取得できない」報告に対応し、`utils/real_audio_recorder.py` の `_finished_callback` を修正。固定で `recording_status=False` にする処理を廃止し、`self.connections[guild_id].recording` の実状態に同期するよう変更。
- 回帰テスト `tests/test_real_audio_recorder_state.py` を新規追加し、(1) 録音継続中は `recording_status` が維持されること、(2) 録音停止時は `False` へ落ちることを確認。
- `python3 -m pytest tests/test_real_audio_recorder_state.py tests/test_real_audio_recorder_buffers.py` と `python3 -m pytest` を実行し、48件のテストが全て成功することを確認。
- `/replay user` で 30秒指定なのに 51秒前後へ伸びる事象を `logs/yomiage.log` で確認（2026-02-15 03:47:53 に `Retrieved 7 chunks` / `Replay audio generated ... 51.5s`）。WaveSink チャンクのオーバーラップ二重連結が原因と判断。
- `utils/replay_buffer_manager.py` を修正し、ユーザー結合時に `chunk.timestamp` と実フレーム長から重複秒数を算出して先頭をスキップするオーバーラップ除去ロジックを追加。
- 同ファイルに `_trim_audio_to_duration` を追加し、`/replay` 生成結果を要求秒数（例: 30秒）以内に末尾優先でトリムするよう変更。
- `tests/test_replay_buffer_manager_audio.py` に重複除去テストとトリムテストを追加し、尺伸び回帰をTDDで固定。
- `python3 -m pytest tests/test_replay_buffer_manager_audio.py tests/test_replay_buffer_integration.py` と `python3 -m pytest` を実行し、50件のテストが全て成功することを確認。
- 30秒指定で機械音が残る報告に対し、`ffmpeg -version` を確認（WSL上 `6.1.1`）し、バージョン起因より録音後処理経路の差分が主因と判断。
- `cogs/recording.py` の `_process_new_replay_async` を修正し、ReplayBufferManager出力をそのまま送信せず `_process_audio_buffer` を必ず通すよう統一。新経路でも既存経路と同じノーマライズ/容量制御を適用。
- `utils/audio_processor.py` の `normalize_audio` フィルターを `adeclip,highpass,lowpass,loudnorm` へ更新し、歪み成分を抑えてからラウドネス調整するよう変更。
- `python3 -m pytest tests/test_replay_buffer_integration.py tests/test_recording_cog_manual_commands.py tests/test_tts_text_limit.py` と `python3 -m pytest` を実行し、50件のテストが全て成功することを確認。

## 2026-02-15
- 「話しているのに `/replay` が音声データなしになる」報告を再調査し、`logs/yomiage.log` で `WaveSink callback returned no audio data` / `sink.audio_data keys: []` が連続発生していることを確認。
- TDDとして `tests/test_real_audio_recorder_recovery.py` を新規追加し、(1) 空コールバック連続時に録音再起動が走ること、(2) 正常な音声取得時に空カウンタがリセットされることを先に失敗で確認。
- `utils/real_audio_recorder.py` に空コールバック監視（`empty_callback_counts`）と自動復旧処理（閾値超過時に `stop_recording/start_recording` でセッション再起動）を実装。
- 自動復旧はクールダウン付きで、Bot以外のメンバーがVCにいる場合のみ実行する制御を追加し、無人時の不要再起動を抑制。
- `README.md` に録音機能の保護仕様（空コールバック連続時の自動再起動）とトラブルシュート項目を追記。
- `python3 -m pytest tests/test_real_audio_recorder_recovery.py`、`python3 -m pytest tests/test_real_audio_recorder_async.py tests/test_real_audio_recorder_buffers.py tests/test_real_audio_recorder_state.py`、`python3 -m pytest` を実行し、52件すべて成功を確認。
- 空コールバック連続時の自動復旧で `Not currently recording audio.` が発生すると再開まで中断していたため、`utils/real_audio_recorder.py` の復旧処理を修正し、停止済みエラーは許容して `start_recording` へ進むよう変更。
- 回帰テストとして `tests/test_real_audio_recorder_recovery.py` に「停止時エラーでも復旧再開が走る」ケースを追加し、`python3 -m pytest` で53件成功を確認。
- さらに運用ログで `Recovery restart failed ... Already recording.` が連発し復旧が止まる事象を確認したため、`utils/real_audio_recorder.py` の復旧処理に「Already recording競合時の1回再試行（stop→start）」を追加。
- `tests/test_real_audio_recorder_recovery.py` に `test_recovery_retries_once_when_start_reports_already_recording` を追加し、競合時でも復旧再開できることをTDDで固定。`python3 -m pytest` で54件成功を確認。
- 機械音原因の切り分け用に `/replay` へ `debug_audio_stages` オプションを追加し、工程別音声（生データ/正規化後/加工後）を保存できるよう `cogs/recording.py` を拡張。
- `RecordingCog._process_audio_buffer` にデバッグ出力引数を追加し、正規化前後と最終加工後のバイト列を取得可能にした。
- `RecordingCog._store_replay_debug_stages` / `_maybe_send_replay_debug_stages` を新設し、`recordings/replay/<GuildID>/debug/` へ3段階WAVとZIPを保存・通知する処理を実装。
- `tests/test_replay_debug_audio_stages.py` を追加し、`debug_audio_stages=true` 実行時に工程別ファイルとZIPが生成されることをTDDで確認。`python3 -m pytest` で55件成功を確認。
- ライブラリ調査として、利用中の `py-cord` が `2.6.1.dev299+g59d48606`（PR #2651相当）であること、ログで音声モード `aead_xchacha20_poly1305_rtpsize` が選択されていることを確認。
- `py-cord` 側の後続修正（PR #2925）との差分を踏まえ、`utils/voice_receive_patch.py` を新設。`VoiceClient.unpack_audio` のRTP判定を互換化し、旧実装の `aead_xchacha20_poly1305_rtpsize` 復号経路を補正するパッチを実装。
- `bot.py` で旧 `patch_voice_decrypt_errors` を廃止し、新しい `apply_voice_receive_patch` を起動時に適用する構成へ変更。
- `tests/test_voice_receive_patch.py` を追加し、(1) RTPマーカービット付きpayloadの受信、(2)非音声payloadの除外、(3)旧rtpsize復号経路の8バイト補正をTDDで検証。
- `python3 -m pytest` を実行し、58件すべて成功を確認。
- `/replay` 実行時に新経路が音声データなしでも旧経路フォールバックで成功するケースで、先に `❌` が出る二重通知を確認。
- `cogs/recording.py` の `_process_new_replay_async` に `suppress_no_data_message` を追加し、フォールバック前提呼び出しでは新経路の失敗メッセージを抑止するよう修正。
- `tests/test_replay_fallback_messaging.py` を追加し、`❌` が先行せず最終結果のみ通知されることをTDDで固定。
- `python3 -m pytest` を実行し、59件すべて成功を確認。
- `/replay` の工程別音声デバッグ機能（`debug_audio_stages`）が不要になったため、`cogs/recording.py` からオプション引数・工程別ファイル保存処理・関連通知処理を削除。
- `RecordingCog._process_audio_buffer` から工程別デバッグ出力引数を削除し、通常の正規化/容量制御フローに一本化。
- 役目を終えた `tests/test_replay_debug_audio_stages.py` を削除し、`tests/test_replay_fallback_messaging.py` の呼び出しシグネチャを現行実装に合わせて更新。
- `README.md` の `/replay` 説明から工程別音声保存オプションの記述を削除。
- `python3 -m pytest` を実行し、58件すべて成功を確認。
- パフォーマンスチューニングとして `AudioChunk` に `pcm_data` キャッシュを追加し、`RecordingCallbackManager.process_audio_data` でWAV解析時に抽出したPCMを保持するよう変更。
- `ReplayBufferManager._process_user_audio` を更新し、`pcm_data` があるチャンクは `wave.open` を再実行せずメタデータとPCMを直接利用する高速経路を追加。
- `ReplayBufferManager._trim_audio_to_duration` を更新し、全フレーム読込ではなく末尾に必要なフレームだけを読み込むよう改善（大きいWAVでのメモリ負荷を低減）。
- 新規テスト `tests/test_recording_callback_manager_pcm_cache.py` を追加し、PCMキャッシュがバッファに保存されることをTDDで固定。
- `tests/test_replay_buffer_manager_audio.py` にPCMキャッシュ利用時の再パース回避テストを追加。
- `python3 -m pytest tests/test_recording_callback_manager_pcm_cache.py tests/test_replay_buffer_manager_audio.py` と `python3 -m pytest` を実行し、60件すべて成功を確認。
- 「Botが既にVC接続中に、別チャンネルへ人が参加すると勝手に移動する」報告に対応するため、`tests/test_voice_auto_join.py` に「別VC参加時は移動しない」回帰テストを追加してTDDで先に失敗を確認。
- `cogs/voice.py` の `handle_user_join` を修正し、接続中チャンネルと異なるVCへの参加イベントでは `move_to` せず現在の接続先を維持するよう変更。
- 起動時の自動参加チェック（`_check_guild_for_auto_join`）でも同方針に揃え、既存接続がある場合の自動移動を抑止。
- `README.md` の基本機能に「既接続中は別VC参加イベントで自動移動しない」仕様を追記。
- `python3 -m pytest tests/test_voice_auto_join.py` と `python3 -m pytest` を実行し、61件すべて成功を確認。
- `/replay` で「過去30秒データなし（最後の記録は約1481秒前）」が返る事象を `logs/yomiage.log` で調査し、`WaveSink callback returned no audio data` が連続して `sink.audio_data keys: []` のままになっていることを確認。
- `utils/real_audio_recorder.py` の復旧ロジックを強化し、空コールバック連続時の軽い再開を複数回試しても改善しない場合は、同一チャンネルへVCを張り直すハードリカバリ（disconnect→connect→録音再開）を実装。
- `tests/test_real_audio_recorder_recovery.py` にハードリカバリへの昇格テストを追加し、既存の復旧テストと合わせてTDDで挙動を固定。
- `README.md` に空コールバック連続時のハードリカバリ仕様を追記。
- `python3 -m pytest tests/test_real_audio_recorder_recovery.py` と `python3 -m pytest` を実行し、62件すべて成功を確認。
- 「2秒以上の無音を削除したい」要望に対応するため、`tests/test_audio_processor_silence_trim.py` を追加し、ノーマライズ用フィルターチェーンで `silenceremove` の有効/無効が切り替わることをTDDで先に失敗確認。
- `utils/audio_processor.py` に `_build_normalize_filter_chain` を追加し、`audio_processing.trim_silence=true` のとき `silenceremove`（`start_duration/stop_duration`）を組み込むよう実装。
- `normalize_audio` で固定文字列ではなくフィルタービルダーを使うよう変更し、無音除去の閾値を設定から制御可能にした。
- `config.yaml` に `audio_processing.trim_silence` / `silence_remove_min_duration` / `silence_threshold_db` を追加（デフォルトで2秒以上無音を除去）。
- `README.md` に `/replay` 正規化時の2秒無音除去仕様を追記。
- `python3 -m pytest tests/test_audio_processor_silence_trim.py` と `python3 -m pytest` を実行し、64件すべて成功を確認。
- 「Botが出入りを繰り返す」報告を `logs/yomiage.log` で調査し、`WaveSink callback returned no audio data` が継続する無音状態でも自動復旧がエスカレートしてVC再接続（ハードリカバリ）を繰り返す経路を確認。
- `tests/test_real_audio_recorder_recovery.py` を更新し、最近の非空音声取得実績が無い場合は復旧をスキップするテストを追加。既存復旧テストには直近音声時刻をセットして期待挙動を維持するよう調整。
- `utils/real_audio_recorder.py` に `RECOVERY_REQUIRES_RECENT_AUDIO_SECONDS` / `_last_non_empty_audio_at` を追加し、最近の非空音声が無いギルドでは自動復旧を抑止してVC出入りループを防止。
- 非空音声を受信したタイミングで `self._last_non_empty_audio_at[guild_id]` を更新し、復旧判定を再開するよう修正。
- `README.md` に「無音時の過剰な自動再接続抑止」仕様を追記。
- `python3 -m pytest tests/test_real_audio_recorder_recovery.py`、`python3 -m pytest tests/test_audio_processor_silence_trim.py tests/test_real_audio_recorder_recovery.py`、`python3 -m pytest` を実行し、65件すべて成功を確認。

## 2026-02-19
- 依存ライブラリを更新するため、`pyproject.toml` の `py-cord[voice]` を PRブランチ参照から `2.7.1` 固定へ変更。
- `UV_PROJECT_ENVIRONMENT=/tmp/yomiagebotex-uv-env uv lock` を実行し、`uv.lock` の依存解決結果を更新（`py-cord 2.7.1` / `PyNaCl 1.6.2` などへ反映）。
- `UV_PROJECT_ENVIRONMENT=/tmp/yomiagebotex-uv-env uv sync --all-extras` 後に `UV_PROJECT_ENVIRONMENT=/tmp/yomiagebotex-uv-env uv run python -m pytest` を実行し、65件すべて成功することを確認。
- `README.md` のTTS機能説明を更新し、入退室挨拶の対応表記を `py-cord 2.7.1` ベースへ修正。
- 変更ファイル: `pyproject.toml`, `uv.lock`, `README.md`, `AGENTS.md`。
- `/replay` 結果を公開投稿できるよう、`cogs/recording.py` に `ReplayShareView`（ボタン）と共通送信ヘルパー `_send_replay_with_share_button` を追加。
- `/replay` の成功返信（新経路・旧経路の両方）をボタン付きエフェメラル送信へ統一し、ボタン押下で同じWAVを通常チャネルへ送信できるようにした。
- 実行者以外のボタン利用を拒否する制御を `ReplayShareView` に追加し、誤操作を防止。
- TDDとして `tests/test_replay_share_view.py` を新規追加し、(1)公開投稿されること、(2)実行者以外は拒否されることを先に失敗で確認してから実装。
- 既存回帰として `tests/test_replay_buffer_integration.py` に `view` 付与の検証を追加。
- `UV_PROJECT_ENVIRONMENT=/tmp/yomiagebotex-uv-env uv run python -m pytest tests/test_replay_buffer_integration.py tests/test_replay_share_view.py` と `UV_PROJECT_ENVIRONMENT=/tmp/yomiagebotex-uv-env uv run python -m pytest` を実行し、67件すべて成功を確認。
- 変更ファイル: `cogs/recording.py`, `tests/test_replay_share_view.py`, `tests/test_replay_buffer_integration.py`, `README.md`, `AGENTS.md`。
- `/replay` の音声連結境界を聞き取りやすくするため、`ReplayBufferManager._process_user_audio` で非重複チャンク間へ0.5秒の無音を挿入する仕様に変更。
- 設定値 `recording.chunk_gap_silence_seconds` を追加し、無音挿入秒数を `config.yaml` で調整可能にした（デフォルト0.5秒）。
- TDDとして `tests/test_replay_buffer_manager_audio.py::test_process_user_audio_parses_variable_wav_header` を更新し、連結時に0.5秒無音が挿入されることを先に失敗で確認してから実装。
- `UV_PROJECT_ENVIRONMENT=/tmp/yomiagebotex-uv-env uv run python -m pytest tests/test_replay_buffer_manager_audio.py` と `UV_PROJECT_ENVIRONMENT=/tmp/yomiagebotex-uv-env uv run python -m pytest` を実行し、67件すべて成功を確認。
- 変更ファイル: `utils/replay_buffer_manager.py`, `tests/test_replay_buffer_manager_audio.py`, `config.yaml`, `README.md`, `AGENTS.md`。

## 2026-02-20
- WSL切断の要因を再調査し、`/var/log/syslog` の `2026-02-21 00:47:15` で `python3` が `anon-rss:18844860kB`（約18GB）を消費してOOM killされた記録を確認。メモリ逼迫が再接続/切断の主因と判断。
- OOM緩和のTDDとして `tests/test_recording_callback_manager_memory_limits.py` を新規追加し、RecordingCallbackManagerで
  1) ユーザー上限超過時に最古チャンクを削除
  2) 全体上限超過時にグローバル最古チャンクを削除
  を先に失敗で確認。
- `utils/recording_callback_manager.py` を改修し、`callback_buffer_max_user_mb` / `callback_buffer_max_guild_mb` / `callback_buffer_max_total_mb` / `callback_max_chunk_size_mb` を反映する `apply_recording_config` を追加。ユーザー・ギルド・全体の3段階メモリ上限で古いチャンクを自動破棄する制御を実装。
- `bot.py` の起動時初期化で `recording_callback_manager.apply_recording_config(self.config.get(\"recording\", {}))` を呼び出し、`config.yaml` の上限値が実行時に有効になるよう接続。
- `config.yaml` の `recording` セクションに上記4設定（MB単位）を追加し、運用で上限値を調整できるようにした。
- `README.md` に RecordingCallbackManager のメモリ上限制御仕様を追記。
- `python3 -m pytest tests/test_recording_callback_manager_memory_limits.py` と `python3 -m pytest tests/test_recording_callback_manager_pcm_cache.py tests/test_replay_buffer_manager_audio.py` を実行し、8件すべて成功を確認。
- OOM再発を抑えるため `config.yaml` の `recording.callback_buffer_max_*_mb` を運用寄りに引き下げ（`user: 32MB / guild: 128MB / total: 512MB`）。
- `README.md` に新しいデフォルト上限値を追記。

## 2026-02-22
- 「勝手にDisconnectする」再発報告を受けて `logs/yomiage.log` を調査し、`2026-02-22 02:06:07` に `RealTimeRecorder: Escalating to hard reconnect...` の直後 `Disconnecting from voice normally` が発生していることを確認。空コールバック連続時の自動復旧がVC切断を誘発していた。
- TDDとして `tests/test_real_audio_recorder_recovery.py` を更新:
  - `test_recovery_does_not_hard_reconnect_when_soft_restart_succeeds` を追加し、`soft restart` が成功する限りハード再接続に昇格しないことを先に失敗で固定。
  - `test_recovery_escalates_to_hard_reconnect_after_repeated_soft_restarts` は、`soft restart` が失敗し続けた場合にのみ昇格する期待へ更新。
- `utils/real_audio_recorder.py` の `_attempt_recover_stuck_recording` を改修し、昇格カウンタを「試行回数」ではなく「連続失敗回数」として扱うよう変更。`soft restart` 成功時はカウンタをリセットし、失敗が閾値に達したときだけ `_attempt_hard_reconnect` を実行。
- `README.md` に「`soft restart` 成功中はハード再接続を実行しない」仕様を追記。
- 実行コマンド:
  - `python3 -m pytest tests/test_real_audio_recorder_recovery.py -q`（失敗→修正後成功）
  - `python3 -m pytest`（71件すべて成功）
- 変更ファイル:
  - `utils/real_audio_recorder.py`
  - `tests/test_real_audio_recorder_recovery.py`
  - `README.md`
  - `AGENTS.md`

## 2026-02-22（メモリ削減）
- 「メモリ使用量を削減したい」要望に対し、設定値・バッファ保持方式・保持時間の3点を同時に見直し。
- TDDとして以下を先に更新して失敗を確認:
  - `tests/test_recording_callback_manager_pcm_cache.py` に「`AudioChunk.data` は空で `pcm_data` を保持する」期待を追加。
  - `tests/test_recording_callback_manager_memory_limits.py` のメモリ見積りをPCM主体へ更新し、`callback_buffer_duration_seconds` 反映テストを追加。
  - `tests/test_real_audio_recorder_state.py` に `buffer_expiration_seconds` / `continuous_buffer_duration_seconds` 反映テストを追加。
- `utils/recording_callback_manager.py` を修正し、WAV解析に成功したチャンクは `AudioChunk.data` へ生WAVを保持せず `pcm_data` 主体で保持するよう変更。加えて `callback_buffer_duration_seconds` を `apply_recording_config` で反映するよう実装。
- `utils/real_audio_recorder.py` に `apply_recording_config` を追加し、`buffer_expiration_seconds` / `continuous_buffer_duration_seconds` を実行時に反映可能にした。
- `cogs/recording.py` で `recording` 設定を `self.recording_manager` と `self.real_time_recorder` の両方へ適用するよう変更。
- `config.yaml` のデフォルトをメモリ節約寄りへ調整:
  - `callback_max_chunk_size_mb: 4`
  - `callback_buffer_max_user_mb: 8`
  - `callback_buffer_max_guild_mb: 32`
  - `callback_buffer_max_total_mb: 128`
  - 追加: `buffer_expiration_seconds: 120` / `continuous_buffer_duration_seconds: 120` / `callback_buffer_duration_seconds: 120`
- `README.md` に新しいデフォルト上限値と保持秒数設定、PCM主体保持の仕様を追記。
- 実行コマンド:
  - `python3 -m pytest tests/test_recording_callback_manager_pcm_cache.py tests/test_recording_callback_manager_memory_limits.py tests/test_real_audio_recorder_state.py -q`（失敗→修正後成功）
  - `python3 -m pytest`（73件すべて成功）
- 変更ファイル:
  - `utils/recording_callback_manager.py`
  - `utils/real_audio_recorder.py`
  - `cogs/recording.py`
  - `config.yaml`
  - `tests/test_recording_callback_manager_pcm_cache.py`
  - `tests/test_recording_callback_manager_memory_limits.py`
  - `tests/test_real_audio_recorder_state.py`
  - `README.md`
  - `AGENTS.md`

## 2026-02-21
- `Decoder Process Killed` が連続出力される報告を受け、`/home/mlove/.local/lib/python3.12/site-packages/discord/opus.py` を調査。`DecodeManager.stop()` が待機ループ内で毎回 `print("Decoder Process Killed")` を実行していることを原因として特定。
- TDDとして `tests/test_voice_receive_patch.py` に `test_voice_receive_patch_suppresses_decode_manager_killed_spam` を追加し、先に失敗（`Decoder Process Killed` が標準出力へ出る）を確認。
- `utils/voice_receive_patch.py` に `DecodeManager.stop` の追加パッチ `_patch_decode_manager_stop` を実装。停止時は短時間だけ排出待ちし、未処理キューを `clear()` したうえで `self._end_thread.set()` へ進めるようにしてスパム出力を抑止。
- 既存の `apply_voice_receive_patch` から上記パッチを適用するよう接続し、受信互換パッチと同時に有効化。
- `README.md` の録音・リプレイ機能へ「`Decoder Process Killed` スパム抑止」仕様を追記。
- 実行コマンド:
  - `python3 -m pytest tests/test_voice_receive_patch.py -q`（失敗→実装後成功）
  - `python3 -m pytest`（70件すべて成功）
- 変更ファイル:
  - `utils/voice_receive_patch.py`
  - `tests/test_voice_receive_patch.py`
  - `README.md`
  - `AGENTS.md`
