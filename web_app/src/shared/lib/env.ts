export type PublicEnvironment = Readonly<{
  apiBaseUrl: string;
  appName: string;
}>;

const defaultEnvironment: PublicEnvironment = {
  apiBaseUrl: '/api/v1',
  appName: 'Tajik HTR Studio',
};

function requireRelativeApiBaseUrl(value: string): string {
  if (!value.startsWith('/') || value.startsWith('//') || value.includes('://')) {
    throw new Error('VITE_API_BASE_URL must be a same-origin path beginning with a single slash.');
  }

  return value.replace(/\/+$/, '') || '/api/v1';
}

export function readPublicEnvironment(
  source: Record<string, string | undefined> = import.meta.env,
): PublicEnvironment {
  return Object.freeze({
    apiBaseUrl: requireRelativeApiBaseUrl(
      source.VITE_API_BASE_URL ?? defaultEnvironment.apiBaseUrl,
    ),
    appName: source.VITE_PUBLIC_APP_NAME?.trim() || defaultEnvironment.appName,
  });
}

export const environment = readPublicEnvironment();
