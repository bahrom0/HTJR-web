import sys
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path().resolve()))

from app.ml.craft_runtime import CraftRuntime
from app.ml.trocr_runtime import TrocrRuntime
from app.services.regions import group_components, reading_order, GroupingParameters, BoundingBox, DetectorComponent
from app.services.images import source_to_rgb

def main():
    models_root = Path("models").resolve()
    image_path = Path(r"../Датасет 1000 реал фотографии/merged_dataset/images/000001.png").resolve()

    with Image.open(image_path) as source:
        image = source_to_rgb(source)

    print("Starting CRAFT...")
    craft = CraftRuntime(models_root, device="cpu")
    craft_result = craft.detect(image)

    components = []
    for index, (box, score) in enumerate(zip(craft_result.boxes, craft_result.scores)):
        left, top, right, bottom = box
        width, height = craft_result.width, craft_result.height
        n_box = BoundingBox(
            max(0.0, min(1.0, left / width)),
            max(0.0, min(1.0, top / height)),
            max(0.0, min(1.0, right / width)),
            max(0.0, min(1.0, bottom / height)),
        )
        components.append(DetectorComponent(f"craft_component_{index}", n_box, max(0.0, min(1.0, score))))

    grouping = GroupingParameters()
    lines = reading_order(group_components(components, grouping), grouping)

    print(f"Found {len(lines)} lines. Starting TrOCR...")
    trocr = TrocrRuntime(models_root, device="cpu")
    trocr.warmup()

    results = []
    for order, line in enumerate(lines):
        # We compute crop bounds, applying a standard padding (like in API)
        padding_fraction = 0.08
        width, height = image.width, image.height
        
        box_width = (line.bbox.right - line.bbox.left) * width
        box_height = (line.bbox.bottom - line.bbox.top) * height
        pad_x = box_height * padding_fraction
        pad_y = box_height * padding_fraction
        
        left = max(0, int(line.bbox.left * width - pad_x))
        top = max(0, int(line.bbox.top * height - pad_y))
        right = min(width, int(line.bbox.right * width + pad_x))
        bottom = min(height, int(line.bbox.bottom * height + pad_y))
        
        crop = image.crop((left, top, right, bottom))
        
        generation = trocr.recognize(crop, num_beams=1, max_new_tokens=128)
        results.append(generation.text)
        print(f"Line {order+1}: {generation.text}")

    print("--- Final Recognized Text ---")
    print("\n".join(results))

if __name__ == "__main__":
    main()
