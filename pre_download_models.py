# pre_download_models.py

from sentence_transformers import SentenceTransformer
import os
import shutil

def download_and_save_model():
    """
    Downloads the specified sentence-transformer model from Hugging Face
    and saves it to a local directory in a self-contained format.
    """
    model_name = 'all-MiniLM-L6-v2'
    # Define the target directory for the final, clean model
    local_model_path = os.path.join('models', model_name)

    # If the final directory already exists, we're done.
    if os.path.exists(local_model_path):
        print(f"Model '{model_name}' already exists at '{local_model_path}'. Skipping.")
        return

    print(f"Downloading and saving model '{model_name}'...")
    
    try:
        # 1. Instantiate the model. This will download it to the default
        #    Hugging Face cache directory (e.g., ~/.cache/huggingface/hub).
        model = SentenceTransformer(model_name)

        # 2. Use the .save() method. This is the crucial step.
        #    It copies all necessary files from the cache into a clean,
        #    self-contained directory structure at the path we specify.
        #    This ensures all config files like '1_Pooling/config.json' are correctly placed.
        model.save(local_model_path)
        
        print(f"Model '{model_name}' saved successfully to '{local_model_path}'.")

    except Exception as e:
        print(f"An error occurred during model download or save: {e}")
        # Clean up a potentially incomplete download
        if os.path.exists(local_model_path):
            shutil.rmtree(local_model_path)
        exit(1)


if __name__ == "__main__":
    # Ensure the parent 'models' directory exists
    if not os.path.exists('models'):
        os.makedirs('models')
    
    download_and_save_model()