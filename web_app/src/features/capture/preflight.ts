const SUPPORTED_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);
export const CLIENT_UPLOAD_MAX_BYTES = 10 * 1024 * 1024;
export const CLIENT_IMAGE_MAX_PIXELS = 40_000_000;
export async function preflightImage(file: File): Promise<string | null> {
  if (!SUPPORTED_TYPES.has(file.type)) return 'Выберите изображение JPEG, PNG или WebP.';
  if (file.size === 0) return 'Файл пуст.';
  if (file.size > CLIENT_UPLOAD_MAX_BYTES)
    return 'Файл больше 10 МБ. Выберите изображение меньшего размера.';
  try {
    const bitmap = await createImageBitmap(file);
    const tooLarge =
      bitmap.width > 12_000 ||
      bitmap.height > 12_000 ||
      bitmap.width * bitmap.height > CLIENT_IMAGE_MAX_PIXELS;
    bitmap.close();
    return tooLarge ? 'Разрешение изображения превышает безопасный предел.' : null;
  } catch {
    return 'Не удалось прочитать изображение. Выберите другой файл.';
  }
}
