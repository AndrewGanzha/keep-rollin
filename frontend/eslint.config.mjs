import vue from 'eslint-plugin-vue'
import tseslint from 'typescript-eslint'

const UI_LIBRARIES = [
  'vuetify',
  'element-plus',
  'naive-ui',
  'quasar',
  '@headlessui/vue',
  '@mantine/*',
  'bootstrap-vue*',
]

/**
 * Запрет межслойных импортов (FSD): слой может зависеть только от нижних.
 * UI-библиотека — только PrimeVue.
 */
const boundaries = (forbidden, hint) => ({
  'no-restricted-imports': [
    'error',
    {
      patterns: [
        ...forbidden.map(group => ({ group: [group], message: hint })),
        ...UI_LIBRARIES.map(group => ({ group: [group], message: 'UI-слой только PrimeVue' })),
      ],
    },
  ],
})

export default tseslint.config(
  {
    ignores: ['dist/**', '.nuxt/**', '.output/**', 'node_modules/**', 'coverage/**', 'app/shared/api/schema.d.ts'],
  },

  ...tseslint.configs.recommended,
  ...vue.configs['flat/recommended'],

  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
        extraFileExtensions: ['.vue'],
        sourceType: 'module',
      },
    },
  },

  {
    rules: {
      'vue/multi-word-component-names': 'off',
      'vue/block-lang': ['error', { script: { lang: 'ts' } }],
      'vue/component-api-style': ['error', ['script-setup']],
      'vue/define-macros-order': ['error', { order: ['defineOptions', 'defineProps', 'defineEmits', 'defineSlots'] }],
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/consistent-type-imports': ['error', { prefer: 'type-imports' }],
      'no-console': ['warn', { allow: ['warn', 'error'] }],
    },
  },

  // Страница — только композиция готовых блоков; импорт другой страницы запрещён
  {
    files: ['app/pages/**/*.vue'],
    rules: boundaries(['~/pages/**'], 'Страницы не импортируют друг друга'),
  },
  {
    files: ['app/features/**'],
    rules: boundaries(['~/widgets/**', '~/pages/**'], 'features → entities/shared'),
  },
  {
    files: ['app/widgets/**'],
    rules: boundaries(['~/pages/**'], 'widgets → features/entities/shared'),
  },
  {
    files: ['app/entities/**'],
    rules: boundaries(['~/features/**', '~/widgets/**', '~/pages/**'], 'entities → shared'),
  },
  {
    files: ['app/shared/**'],
    rules: boundaries(['~/entities/**', '~/features/**', '~/widgets/**', '~/pages/**'], 'shared не зависит от слоёв выше'),
  },
)
