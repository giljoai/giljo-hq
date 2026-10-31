# Bundled tiktoken encodings

Shipped gzip-compressed so vision-document chunking works on an offline install.
`tiktoken_bundle.py` unpacks them into a per-user cache and checks the sha256 of the
uncompressed bytes. tiktoken names each file sha1(blob URL).
