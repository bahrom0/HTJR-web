import sys
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path().resolve()))

from app.ml.trocr_runtime import TrocrRuntime
from app.services.images import source_to_rgb

def main():
    models_root = Path("models").resolve()
    image_path = Path(r"../Датасет 1000 реал фотографии/merged_dataset/images/000001.png").resolve()

    with Image.open(image_path) as source:
        # source_to_rgb ensures it's opaque and properly oriented
        image = source_to_rgb(source)

    print(f"Loaded image: {image_path.name}, size: {image.size}")
    print("Starting TrOCR...")
    trocr = TrocrRuntime(models_root, device="cpu")
    trocr.warmup()

    # Pass the entire image to TrOCR since it's already a line crop
    generation = trocr.recognize(image, num_beams=1, max_new_tokens=128)
    
    print("--- Final Recognized Text ---")
    with open("result.txt", "w", encoding="utf-8") as f:
        f.write(generation.text)
    print("Result saved to result.txt")

if __name__ == "__main__":
    main()
