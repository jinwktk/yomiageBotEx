"""
音声処理ユーティリティ
FFmpegによるノーマライズ処理、フィルタリング等
"""

import asyncio
import logging
import tempfile
import os
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class AudioProcessor:
    """音声処理クラス（軽量化重視）"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.ffmpeg_available = self._check_ffmpeg()
        self.normalize_enabled = config.get("audio_processing", {}).get("normalize", True)
        self.target_level = config.get("audio_processing", {}).get("target_level", -16.0)  # dBFS
        
    def _check_ffmpeg(self) -> bool:
        """FFmpegの利用可能性をチェック"""
        try:
            subprocess.run(["ffmpeg", "-version"], 
                         capture_output=True, check=True, timeout=5)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("FFmpeg not available, audio processing will be disabled")
            return False
    
    async def extract_time_range(self, input_path: str, start_seconds: float, duration_seconds: float, output_path: Optional[str] = None) -> Optional[str]:
        """
        音声ファイルから指定した時間範囲を切り出し
        
        Args:
            input_path: 入力音声ファイルパス
            start_seconds: 開始時刻（秒）
            duration_seconds: 切り出し時間（秒）
            output_path: 出力パス（省略時は一時ファイル）
            
        Returns:
            処理済みファイルパス（失敗時はNone）
        """
        if not self.ffmpeg_available:
            logger.warning("FFmpeg not available, cannot extract time range")
            return input_path
            
        if not os.path.exists(input_path):
            logger.error(f"Input file not found: {input_path}")
            return None
            
        try:
            if output_path is None:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                    output_path = tmp_file.name
            
            # FFmpegで時間範囲を切り出し
            cmd = [
                "ffmpeg", "-y",  # 出力ファイルを上書き
                "-i", input_path,
                "-ss", str(start_seconds),  # 開始時刻
                "-t", str(duration_seconds),  # 切り出し時間
                "-c", "copy",  # 再エンコードなし（高速処理）
                output_path
            ]
            
            logger.debug(f"Running FFmpeg time extraction: {' '.join(cmd)}")
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
            
            if process.returncode == 0:
                logger.info(f"Successfully extracted {duration_seconds}s from {start_seconds}s: {output_path}")
                return output_path
            else:
                logger.error(f"FFmpeg time extraction failed: {stderr.decode()}")
                return None
                
        except asyncio.TimeoutError:
            logger.error("FFmpeg time extraction timed out")
            return None
        except Exception as e:
            logger.error(f"Error during time extraction: {e}")
            return None

    async def normalize_audio(self, input_path: str, output_path: Optional[str] = None) -> Optional[str]:
        """
        音声ファイルをノーマライズ処理
        
        Args:
            input_path: 入力音声ファイルパス
            output_path: 出力パス（省略時は一時ファイル）
            
        Returns:
            処理済みファイルパス（失敗時はNone）
        """
        if not self.ffmpeg_available or not self.normalize_enabled:
            return input_path
            
        if not os.path.exists(input_path):
            logger.error(f"Input file not found: {input_path}")
            return None
            
        try:
            # 出力パスが指定されていない場合は一時ファイルを作成
            if not output_path:
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                    output_path = temp_file.name
            
            # FFmpegコマンドでノーマライズ処理
            # de-clip + loudnorm で歪みを抑えつつラウドネス正規化
            cmd = [
                "ffmpeg", "-y",  # -y: 上書き確認なし
                "-i", input_path,
                "-af", f"adeclip,highpass=f=80,lowpass=f=8000,loudnorm=I={self.target_level}:TP=-2.0:LRA=11",
                "-c:a", "pcm_s16le",  # 16-bit PCM
                "-ar", "48000",  # 48kHz（Discord標準）
                "-ac", "2",  # ステレオ
                output_path
            ]
            
            # 非同期でFFmpegを実行
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            
            if process.returncode == 0:
                logger.debug(f"Audio normalized successfully: {input_path} -> {output_path}")
                return output_path
            else:
                logger.error(f"FFmpeg normalization failed: {stderr.decode()}")
                return input_path
                
        except asyncio.TimeoutError:
            logger.error("Audio normalization timeout")
            return input_path
        except Exception as e:
            logger.error(f"Audio normalization error: {e}")
            return input_path
    
    async def apply_audio_filters(self, input_path: str, output_path: Optional[str] = None,
                                filters: Optional[list] = None) -> Optional[str]:
        """
        音声フィルターを適用
        
        Args:
            input_path: 入力音声ファイルパス
            output_path: 出力パス（省略時は一時ファイル）
            filters: 適用するフィルターのリスト
            
        Returns:
            処理済みファイルパス（失敗時はNone）
        """
        if not self.ffmpeg_available:
            return input_path
            
        if not filters:
            # デフォルトフィルター：ノイズ除去とコンプレッサー
            filters = [
                "highpass=f=80",  # ローカットフィルター
                "lowpass=f=8000",  # ハイカットフィルター
                "compand=0.1|0.1:1|1:-90/-60|-60/-40|-40/-30|-20/-20:6:0:-90:0.2"  # コンプレッサー
            ]
        
        try:
            if not output_path:
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                    output_path = temp_file.name
            
            # フィルターチェーンを構築
            filter_chain = ",".join(filters)
            
            cmd = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-af", filter_chain,
                "-c:a", "pcm_s16le",
                "-ar", "48000",
                "-ac", "2",
                output_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            
            if process.returncode == 0:
                logger.debug(f"Audio filters applied successfully: {input_path} -> {output_path}")
                return output_path
            else:
                logger.error(f"FFmpeg filtering failed: {stderr.decode()}")
                return input_path
                
        except Exception as e:
            logger.error(f"Audio filtering error: {e}")
            return input_path
    
    async def merge_audio_files(self, input_files: list, output_path: str, 
                              normalize: bool = True) -> bool:
        """
        複数の音声ファイルをマージ
        
        Args:
            input_files: 入力ファイルのリスト
            output_path: 出力ファイルパス
            normalize: マージ後にノーマライズするか
            
        Returns:
            成功時True、失敗時False
        """
        if not self.ffmpeg_available or not input_files:
            return False
            
        try:
            # FFmpegコマンドを構築
            cmd = ["ffmpeg", "-y"]
            
            # 入力ファイルを追加
            for file_path in input_files:
                cmd.extend(["-i", file_path])
            
            # フィルターコンプレックスでミキシング
            filter_complex = f"amix=inputs={len(input_files)}:duration=longest"
            if normalize:
                filter_complex += f",loudnorm=I={self.target_level}:TP=-1.5:LRA=11"
            
            cmd.extend([
                "-filter_complex", filter_complex,
                "-c:a", "pcm_s16le",
                "-ar", "48000",
                "-ac", "2",
                output_path
            ])
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
            
            if process.returncode == 0:
                logger.info(f"Audio files merged successfully: {len(input_files)} files -> {output_path}")
                return True
            else:
                logger.error(f"FFmpeg merge failed: {stderr.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"Audio merge error: {e}")
            return False
    
    async def get_audio_info(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        音声ファイルの情報を取得
        
        Args:
            file_path: 音声ファイルパス
            
        Returns:
            音声情報辞書（失敗時はNone）
        """
        if not self.ffmpeg_available:
            return None
            
        try:
            cmd = [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                file_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
            
            if process.returncode == 0:
                import json
                info = json.loads(stdout.decode())
                
                # 音声ストリーム情報を抽出
                audio_stream = None
                for stream in info.get("streams", []):
                    if stream.get("codec_type") == "audio":
                        audio_stream = stream
                        break
                
                if audio_stream:
                    return {
                        "duration": float(audio_stream.get("duration", 0)),
                        "sample_rate": int(audio_stream.get("sample_rate", 0)),
                        "channels": int(audio_stream.get("channels", 0)),
                        "codec": audio_stream.get("codec_name", "unknown"),
                        "bit_rate": int(audio_stream.get("bit_rate", 0)),
                        "size": int(info.get("format", {}).get("size", 0))
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get audio info: {e}")
            return None
    
    def cleanup_temp_files(self, *file_paths):
        """一時ファイルのクリーンアップ"""
        for file_path in file_paths:
            try:
                if file_path and os.path.exists(file_path):
                    os.unlink(file_path)
                    logger.debug(f"Cleaned up temp file: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp file {file_path}: {e}")
