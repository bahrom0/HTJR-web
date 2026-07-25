ALTER TABLE pages ADD COLUMN preparation_confirmed_recipe_hash TEXT;
ALTER TABLE pages ADD COLUMN preparation_confirmed_at TEXT;

CREATE INDEX idx_pages_preparation_confirmation
  ON pages(preparation_confirmed_recipe_hash)
  WHERE preparation_confirmed_recipe_hash IS NOT NULL;
