// Derived from official plugin-creator 4bd8022 (classic JSX + host globals).
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteExternalsPlugin } from 'vite-plugin-externals';

const externalLibs = { react: 'React', 'react-dom': 'ReactDOM', '@mantine/core': 'MantineCore', '@mantine/hooks': 'MantineHooks' };
export default defineConfig({
  plugins: [react({ jsxRuntime: 'classic' }), viteExternalsPlugin(externalLibs)],
  build: {
    target: 'esnext', outDir: '../production_capacity/static', emptyOutDir: true,
    rollupOptions: {
      input: './src/Capacity.tsx', external: Object.keys(externalLibs),
      preserveEntrySignatures: 'exports-only',
      output: { entryFileNames: 'Capacity.js', globals: externalLibs }
    }
  }
});
