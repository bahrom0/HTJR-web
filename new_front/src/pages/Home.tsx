import { Link } from 'react-router-dom';
import { useTranslation } from '../lib/i18n';
import { useAppStore } from '../lib/store';
import { Plus, ArrowRight, FileText } from 'lucide-react';
import { Reveal, StaggerContainer, StaggerItem } from '../components/Animations';
import { motion } from 'motion/react';

const MotionLink = motion.create(Link);

export function Home() {
  const { t, language } = useTranslation();
  const documents = useAppStore(state => state.documents);

  const isRu = language === 'ru';

  const recentDocs = documents.slice(0, 4);

  return (
    <Reveal className="flex flex-col gap-16 md:gap-24">
      <section className="flex flex-col gap-6 max-w-3xl">
        <h1 className="h1">
          <span className="opacity-60 block text-2xl md:text-3xl mb-3 font-normal">
            {isRu ? 'Рабочая панель' : 'Workspace'}
          </span>
          {isRu ? 'Готовы распознать новый документ?' : 'Ready to recognize a new manuscript?'}
        </h1>
        <p className="text-base md:text-lg opacity-70">
          {isRu
            ? 'Загрузите изображение рукописи или страницы книги для автоматического распознавания текста нейросетью.'
            : 'Upload a manuscript photo or scanned book page to extract text automatically.'}
        </p>
        
        <div className="mt-2">
          <MotionLink whileTap={{ scale: 0.96 }} to="/recognition/new" className="button-primary inline-flex items-center gap-3 text-lg px-8 py-4 shadow-md">
            <Plus className="w-5 h-5" />
            {t('recognizeNewPage')}
          </MotionLink>
        </div>
      </section>

      <section className="flex flex-col gap-8">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-light">{t('recentDocuments')}</h2>
          </div>
          {documents.length > 0 && (
            <MotionLink whileTap={{ scale: 0.96 }} to="/documents" className="text-sm opacity-60 hover:opacity-100 flex items-center gap-2 transition-opacity">
              {t('viewAll')} <ArrowRight className="w-4 h-4" />
            </MotionLink>
          )}
        </div>

        {recentDocs.length === 0 ? (
          <div className="glass-surface p-12 text-center rounded-[32px] border border-black/5 dark:border-white/5">
            <p className="opacity-60">{t('noDocuments')}</p>
            <div className="mt-4">
              <MotionLink whileTap={{ scale: 0.96 }} to="/recognition/new" className="button-secondary text-sm px-5 py-2 inline-flex items-center gap-2">
                <Plus className="w-4 h-4" />
                {t('recognizeNewPage')}
              </MotionLink>
            </div>
          </div>
        ) : (
          <StaggerContainer className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {recentDocs.map(doc => (
              <StaggerItem key={doc.id}>
                <MotionLink 
                  whileTap={{ scale: 0.96 }}
                  to={doc.step === 'result' ? `/documents/${doc.id}` : `/documents/${doc.id}/pages/1/${doc.step}`}
                  className="glass-surface p-6 rounded-[28px] hover:shadow-card transition-shadow flex flex-col gap-6 block h-full border border-black/5 dark:border-white/5"
                >
                  <div className="aspect-square bg-black/5 dark:bg-white/5 rounded-2xl flex items-center justify-center overflow-hidden">
                    {doc.thumbnail ? (
                      <img src={doc.thumbnail} alt="" className="w-full h-full object-cover rounded-2xl opacity-90" />
                    ) : (
                      <FileText className="w-8 h-8 opacity-20" />
                    )}
                  </div>
                  <div>
                    <h3 className="font-medium truncate">{doc.name}</h3>
                    <div className="flex justify-between items-center mt-2 text-sm opacity-60">
                      <span>{new Date(doc.updatedAt).toLocaleDateString()}</span>
                      <span className="capitalize">{doc.status}</span>
                    </div>
                  </div>
                </MotionLink>
              </StaggerItem>
            ))}
          </StaggerContainer>
        )}
      </section>
    </Reveal>
  );
}
