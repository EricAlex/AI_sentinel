# chroma/Dockerfile

# Use the official ChromaDB image as our starting point
FROM chromadb/chroma

# Switch to the root user to install packages
USER root

# Run the package manager to update and install curl.
# The --no-install-recommends flag keeps the image smaller.
# We chain the commands with && to ensure cleanup happens in the same layer.
RUN apt-get update && apt-get install -y curl --no-install-recommends && rm -rf /var/lib/apt/lists/*

# Switch back to the default non-root user if needed (good practice, though may not be necessary for chroma)
# USER chroma 