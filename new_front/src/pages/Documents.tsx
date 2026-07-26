import { Link } from 'react-router-dom';
import { useTranslation } from '../lib/i18n';
import { useAppStore } from '../lib/store';
import { FileText, MoreVertical, Plus } from 'lucide-react';
import { Reveal, StaggerContainer, StaggerItem, AnimatedButton } from '../components/Animations';
import { motion } from 'motion/react';

const MotionLink = motion.create(Link);

export function Documents() {
  const { t } = useTranslation();
  const documents = useAppStore(state => state.documents);

  return (
    <Reveal className="flex flex-col gap-6 md:gap-12 max-w-5xl mx-auto">
      <div className="flex justify-between items-center">
        <h1 className="h2 text-2xl md:text-4xl">{t('documents')}</h1>
        <MotionLink whileTap={{ scale: 0.96 }} to="/recognition/new" className="button-primary inline-flex items-center gap-2 px-4 md:px-6 min-h-[44px] md:min-h-[54px] text-xs md:text-sm">
           <Plus className="w-4 h-4" /> {t('newDocument')}
        </MotionLink>
      </div>

      <StaggerContainer className="flex flex-col gap-3 md:gap-4">
        {documents.map(doc => (
          <StaggerItem key={doc.id} className="glass-surface p-3.5 md:p-6 rounded-2xl md:rounded-[24px] flex flex-col md:flex-row gap-3 md:gap-6 md:items-center justify-between group hover:shadow-card transition-shadow">
            <div className="flex items-center gap-3 md:gap-6 min-w-0 flex-1">
              <div className="w-11 h-11 md:w-16 md:h-16 bg-black/5 dark:bg-white/5 rounded-xl md:rounded-[18px] flex items-center justify-center shrink-0">
                 <FileText className="w-5 h-5 md:w-6 md:h-6 opacity-30" />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="font-medium text-sm md:text-lg truncate">{doc.name}</h3>
                <div className="flex gap-3 mt-0.5 md:mt-1 text-xs md:text-sm opacity-60">
                  <span>{new Date(doc.updatedAt).toLocaleDateString()}</span>
                  <span className="capitalize">{doc.status}</span>
                </div>
              </div>
            </div>
            
            <div className="flex items-center justify-between md:justify-end gap-2 md:gap-4 pt-2 md:pt-0 border-t md:border-t-0 border-black/5 dark:border-white/5">
              <MotionLink 
                whileTap={{ scale: 0.96 }}
                to={doc.step === 'result' ? `/documents/${doc.id}` : `/documents/${doc.id}/pages/1/${doc.step}`}
                className="button-secondary px-4 py-2 min-h-[38px] md:min-h-[52px] text-xs md:text-sm flex-1 md:flex-initial text-center justify-center"
              >
                {doc.status === 'ready' ? t('open') : t('continue')}
              </MotionLink>
              <AnimatedButton className="p-2 md:p-3 opacity-40 hover:opacity-100 transition-opacity rounded-full">
                <MoreVertical className="w-4 h-4 md:w-5 md:h-5" />
              </AnimatedButton>
            </div>
          </StaggerItem>
        ))}
      </StaggerContainer>
    </Reveal>
  );
}
