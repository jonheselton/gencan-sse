from gencan_sse.chunker import chunk_sentences

chunks = chunk_sentences("Hello there. \n\n How are you?")
print("Chunks:", repr(chunks))

chunks2 = chunk_sentences("👍 \n\n ")
print("Chunks2:", repr(chunks2))

