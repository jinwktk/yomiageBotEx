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
