"""Estratégias de chunking de streaming, buffers de áudio e controle de Barge-in."""

import re
import asyncio
from typing import AsyncGenerator, List, Optional
from voice_lab.contracts.events import TextChunkEvent, BargeInEvent


class TextSentenceChunker:
    """Chunker sintático que quebra streaming de tokens em frases para envio imediato ao TTS."""
    
    def __init__(self, first_chunk_min_words: int = 4):
        self.first_chunk_min_words = first_chunk_min_words
        self.buffer = ""
        self.chunk_index = 0
        self.is_first_chunk = True
        
        self.sentence_delimiter = re.compile(r"([.!?\n]+)\s*")
        self.early_delimiter = re.compile(r"([,;:]+)\s*")

    def process_token(self, token: str, session_id: str, turn_id: str) -> List[TextChunkEvent]:
        self.buffer += token
        events: List[TextChunkEvent] = []

        if self.is_first_chunk:
            words = self.buffer.split()
            if len(words) >= self.first_chunk_min_words:
                match = self.early_delimiter.search(self.buffer)
                if match:
                    cut_pos = match.end()
                    chunk_text = self.buffer[:cut_pos].strip()
                    self.buffer = self.buffer[cut_pos:]
                    self.is_first_chunk = False
                    
                    if chunk_text:
                        events.append(self._create_event(chunk_text, session_id, turn_id, False))
                        return events

        match = self.sentence_delimiter.search(self.buffer)
        if match:
            cut_pos = match.end()
            chunk_text = self.buffer[:cut_pos].strip()
            self.buffer = self.buffer[cut_pos:]
            self.is_first_chunk = False
            
            if chunk_text:
                events.append(self._create_event(chunk_text, session_id, turn_id, False))

        return events

    def flush(self, session_id: str, turn_id: str) -> Optional[TextChunkEvent]:
        residual = self.buffer.strip()
        self.buffer = ""
        if residual:
            return self._create_event(residual, session_id, turn_id, True)
        return None

    def _create_event(self, text: str, session_id: str, turn_id: str, is_final: bool) -> TextChunkEvent:
        event = TextChunkEvent(
            session_id=session_id,
            turn_id=turn_id,
            chunk_index=self.chunk_index,
            text_content=text,
            is_final_chunk=is_final
        )
        self.chunk_index += 1
        return event


class BargeInController:
    """Gerencia o ciclo de cancelamento limpo por interrupção (Barge-in)."""

    def __init__(self):
        self._active_turn_id: Optional[str] = None
        self._cancellation_token = asyncio.Event()
        self._audio_queue: asyncio.Queue = asyncio.Queue()
        self._active_tasks: List[asyncio.Task] = []

    def start_turn(self, turn_id: str) -> None:
        self._active_turn_id = turn_id
        self._cancellation_token.clear()
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._active_tasks.clear()

    @property
    def is_cancelled(self) -> bool:
        return self._cancellation_token.is_set()

    def register_task(self, task: asyncio.Task) -> None:
        self._active_tasks.append(task)

    def trigger_barge_in(self, session_id: str, turn_id: str) -> BargeInEvent:
        self._cancellation_token.set()
        
        discarded_tasks = 0
        for task in self._active_tasks:
            if not task.done():
                task.cancel()
                discarded_tasks += 1
                
        discarded_audio = 0
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
                discarded_audio += 1
            except asyncio.QueueEmpty:
                break
                
        event = BargeInEvent(
            session_id=session_id,
            turn_id=turn_id,
            interrupted_turn_id=self._active_turn_id or turn_id,
            discarded_audio_chunks=discarded_audio,
            metadata={"cancelled_tasks": discarded_tasks}
        )
        return event

    async def queue_audio(self, audio_chunk: bytes) -> bool:
        if self.is_cancelled:
            return False
        await self._audio_queue.put(audio_chunk)
        return True

    async def get_next_audio(self) -> Optional[bytes]:
        if self.is_cancelled:
            return None
        return await self._audio_queue.get()
