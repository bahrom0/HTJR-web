import { RouterProvider } from 'react-router-dom';

import { router } from '@app/router';
import { ThemeProvider } from '@shared/theme/ThemeProvider';
import { AccessProvider } from '@shared/access/AccessProvider';

export function App() {
  return (
    <ThemeProvider>
      <AccessProvider><RouterProvider router={router} /></AccessProvider>
    </ThemeProvider>
  );
}
