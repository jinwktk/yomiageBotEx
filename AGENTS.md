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
