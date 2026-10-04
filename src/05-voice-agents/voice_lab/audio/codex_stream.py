"""Pipeline de Streaming assíncrono conectando o Proxy do Codex ao Chunker sintático e TTS."""

import time
import asyncio
from typing import Any, AsyncGenerator, Callable, List
from voice_lab.audio.stream import TextSentenceChunker, BargeInController
from voice_lab.contracts.events import TextChunkEvent


async def stream_and_chunk_response(
    token_stream: AsyncGenerator[str, None],
    session_id: str,
    turn_id: str,
    chunker: TextSentenceChunker,
    barge_in_ctrl: BargeInController,
    on_sentence_ready: Callable[[TextChunkEvent], Any],
) -> List[TextChunkEvent]:
    emitted_chunks: List[TextChunkEvent] = []

    async for token in token_stream:
        if barge_in_ctrl.is_cancelled:
            break

        events = chunker.process_token(token, session_id, turn_id)
        for ev in events:
            emitted_chunks.append(ev)
            asyncio.create_task(on_sentence_ready(ev))

    if not barge_in_ctrl.is_cancelled:
        final_ev = chunker.flush(session_id, turn_id)
        if final_ev:
            emitted_chunks.append(final_ev)
            asyncio.create_task(on_sentence_ready(final_ev))

    return emitted_chunks
