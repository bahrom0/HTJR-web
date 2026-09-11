import { Link } from 'react-router-dom';
import { useTranslation } from '../lib/i18n';
import { ArrowRight, Sparkles, FileText, ShieldCheck, Zap } from 'lucide-react';
import { Reveal, StaggerContainer, StaggerItem, AnimatedButton } from '../components/Animations';
import { motion } from 'motion/react';

const MotionLink = motion.create(Link);

export function Landing() {
  const { t, language } = useTranslation();

  const isRu = language === 'ru';

  return (
    <Reveal className="flex flex-col items-center justify-center py-12 md:py-20 gap-16 md:gap-24 max-w-5xl mx-auto text-center">
      {/* Hero Section */}
      <div className="flex flex-col items-center gap-6 max-w-3xl">
        <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full glass-surface text-xs md:text-sm font-medium opacity-80 mb-2">
          <Sparkles className="w-4 h-4 text-emerald-500" />
          <span>
            {isRu ? 'Интеллектуальное распознавание рукописей' : 'Intelligent Manuscript & Document OCR'}
          </span>
        </div>

        <h1 className="text-4xl md:text-6xl lg:text-7xl font-light tracking-tight leading-tight">
          Tajik HTR <span className="font-serif italic font-normal">Studio</span>
        </h1>

        <p className="text-lg md:text-xl opacity-70 leading-relaxed max-w-2xl">
          {isRu
            ? 'Система искусственного интеллекта для точного распознавания таджикских рукописных текстов, архивных документов и редких изданий.'
            : 'AI-powered platform for precise recognition of Tajik handwritten manuscripts, historical archives, and printed texts.'}
        </p>

        <div className="flex flex-col sm:flex-row gap-4 mt-6 w-full sm:w-auto justify-center">
          <MotionLink
            whileTap={{ scale: 0.96 }}
            to="/dashboard"
            className="button-primary inline-flex items-center justify-center gap-3 text-lg px-8 py-4 shadow-lg hover:shadow-xl transition-all"
          >
            <span>{isRu ? 'Начать распознавать' : 'Start Recognition'}</span>
            <ArrowRight className="w-5 h-5" />
          </MotionLink>

          <MotionLink
            whileTap={{ scale: 0.96 }}
            to="/recognition/new"
            className="button-secondary inline-flex items-center justify-center gap-2 text-lg px-8 py-4"
          >
            <span>{isRu ? 'Загрузить файл' : 'Upload Image'}</span>
          </MotionLink>
        </div>
      </div>

      {/* Feature Cards */}
      <StaggerContainer className="grid grid-cols-1 md:grid-cols-3 gap-6 w-full text-left">
        <StaggerItem>
          <div className="glass-surface p-8 rounded-[32px] flex flex-col gap-4 h-full">
            <div className="w-12 h-12 rounded-2xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 flex items-center justify-center">
              <Zap className="w-6 h-6" />
            </div>
            <h3 className="text-xl font-medium">
              {isRu ? 'Быстрое ИИ-распознавание' : 'Fast AI Recognition'}
            </h3>
            <p className="text-sm opacity-60 leading-relaxed">
              {isRu
                ? 'Мгновенный анализ страницы без очередей и задержек с прямой обработкой текста нейросетью.'
                : 'Direct synchronous page recognition with advanced neural models designed for accuracy.'}
            </p>
          </div>
        </StaggerItem>

        <StaggerItem>
          <div className="glass-surface p-8 rounded-[32px] flex flex-col gap-4 h-full">
            <div className="w-12 h-12 rounded-2xl bg-blue-500/10 text-blue-600 dark:text-blue-400 flex items-center justify-center">
              <ShieldCheck className="w-6 h-6" />
            </div>
            <h3 className="text-xl font-medium">
              {isRu ? 'Без авторизации' : 'No Account Needed'}
            </h3>
            <p className="text-sm opacity-60 leading-relaxed">
              {isRu
                ? 'Работайте свободно и сразу. Ваши документы привязаны к вашей локальной сессии без паролей.'
                : 'Free and instant access. Work directly with private anonymous sessions on your device.'}
            </p>
          </div>
        </StaggerItem>

        <StaggerItem>
          <div className="glass-surface p-8 rounded-[32px] flex flex-col gap-4 h-full">
            <div className="w-12 h-12 rounded-2xl bg-purple-500/10 text-purple-600 dark:text-purple-400 flex items-center justify-center">
              <FileText className="w-6 h-6" />
            </div>
            <h3 className="text-xl font-medium">
              {isRu ? 'Редактор и экспорт' : 'Editor & Export'}
            </h3>
            <p className="text-sm opacity-60 leading-relaxed">
              {isRu
                ? 'Интуитивная правка распознанного текста рядом с оригиналом и сохранение в TXT, Word или PDF.'
                : 'Side-by-side verification with image regions and instant export to TXT, Word, or PDF.'}
            </p>
          </div>
        </StaggerItem>
      </StaggerContainer>
    </Reveal>
  );
}
