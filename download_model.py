# download_model.py

from sentence_transformers import SentenceTransformer

def main():
    """
    This script's sole purpose is to download and cache the sentence-transformer model
    during the Docker image build process. This ensures the model is "baked into" the
    final image and doesn't need to be downloaded at runtime.
    """
    model_name = 'all-MiniLM-L6-v2'
    print(f"Downloading and caching sentence-transformer model: {model_name}")
    
    try:
        # This line will download the model and store it in the default cache location.
        SentenceTransformer(model_name)
        print("Model downloaded and cached successfully.")
    except Exception as e:
        print(f"An error occurred while downloading the model: {e}")
        # Exit with a non-zero status code to fail the Docker build if download fails
        exit(1)

if __name__ == "__main__":
    main()