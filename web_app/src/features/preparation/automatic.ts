import { createRecognitionJob, type JobSnapshot } from '@entities/job';
import type { ApiResult } from '@shared/api/client';

import { confirmPreparation, getPreparation, previewPreparation } from './api';
import { defaultPreparationRecipe, type PreparationState } from './model';

export type AutomaticPreparationPhase = 'quality' | 'confirming' | 'detecting';

type AutomaticRecognitionOptions = Readonly<{
  signal?: AbortSignal;
  onPhase?: (phase: AutomaticPreparationPhase) => void;
}>;

/**
 * Uses the canonical server flow while collapsing its setup screens into one
 * user action. Existing prepared/confirmed state is reused so a refresh does
 * not create a second page revision or recognition job.
 */
export async function startAutomaticRecognition(
  pageId: string,
  csrfToken: string,
  options: AutomaticRecognitionOptions = {},
): Promise<ApiResult<JobSnapshot>> {
  options.onPhase?.('quality');
  const current = await getPreparation(pageId, options.signal);
  if (!current.ok) return current;

  let preparation: PreparationState = current.value;
  if (!preparation.preparedAsset) {
    const preview = await previewPreparation(
      pageId,
      preparation.recipe ?? defaultPreparationRecipe,
      csrfToken,
    );
    if (!preview.ok) return preview;
    preparation = preview.value;
  }

  if (!preparation.confirmed) {
    options.onPhase?.('confirming');
    const confirmed = await confirmPreparation(pageId, preparation.revision, csrfToken);
    if (!confirmed.ok) return confirmed;
    preparation = confirmed.value;
  }

  options.onPhase?.('detecting');
  return createRecognitionJob(
    pageId,
    `recognition:${pageId}:${preparation.revision}`,
    csrfToken,
    options.signal,
  );
}
