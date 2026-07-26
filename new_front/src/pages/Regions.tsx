import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from '../lib/i18n';
import { useAppStore } from '../lib/store';
import { Plus, Trash2, Move, Type } from 'lucide-react';
import { Reveal, AnimatedButton } from '../components/Animations';

export function Regions() {
  const { t } = useTranslation();
  const { documentId } = useParams();
  const navigate = useNavigate();
  const updateDocument = useAppStore(state => state.updateDocument);
  const documents = useAppStore(state => state.documents);
  const doc = documents.find(d => d.id === documentId);
  
  const handleContinue = () => {
    if (documentId) {
      updateDocument(documentId, { step: 'processing', status: 'processing' });
      navigate(`/documents/${documentId}/pages/1/processing`);
    }
  };

  return (
    <Reveal className="flex flex-col gap-4 md:gap-8 min-h-[calc(100vh-120px)] md:h-[calc(100vh-180px)]">
      {/* Header */}
      <div className="flex justify-between items-center gap-2 pb-2 md:pb-0 border-b md:border-none border-black/5 dark:border-white/5">
        <div>
          <h1 className="text-lg md:text-2xl font-medium">{t('findLines')}</h1>
          <p className="opacity-60 text-xs md:text-sm mt-0.5">{doc?.name || t('verifyRegions')}</p>
        </div>
        <div className="flex items-center gap-2">
           <AnimatedButton onClick={() => navigate(-1)} className="button-secondary px-3 py-1.5 md:px-5 md:py-2 text-xs md:text-sm min-h-[38px] md:min-h-[46px]">{t('cancel')}</AnimatedButton>
           <AnimatedButton onClick={handleContinue} className="button-primary px-4 py-1.5 md:px-6 md:py-2 text-xs md:text-sm min-h-[38px] md:min-h-[46px]">{t('recognizeText')}</AnimatedButton>
        </div>
      </div>
      
      {/* Main Grid */}
      <div className="flex flex-col md:flex-row gap-4 md:gap-6 flex-1 min-h-0">
        {/* Photo Preview Container */}
        <div className="flex-1 glass-surface rounded-2xl md:rounded-[32px] flex items-center justify-center p-4 md:p-6 overflow-hidden relative min-h-[280px] sm:min-h-[340px] md:min-h-0">
           <div className="w-full h-full flex items-center justify-center p-2 relative">
             <div className="aspect-[3/4] w-full max-w-[240px] xs:max-w-[280px] sm:max-w-[340px] md:max-w-[380px] bg-[#f8f5ee] dark:bg-[#22201c] text-[#2c261e] dark:text-[#ece6da] rounded-xl shadow-lg border border-black/10 dark:border-white/10 p-4 sm:p-6 flex flex-col gap-3 relative overflow-hidden">
                {/* Vintage paper stamp / header */}
                <div className="flex justify-between items-center border-b border-black/10 dark:border-white/10 pb-2">
                  <span className="text-[10px] sm:text-xs font-mono uppercase tracking-wider opacity-60">АРХИВ Nº 1904/08</span>
                  <div className="w-3 h-3 rounded-full border border-current opacity-40 flex items-center justify-center text-[8px]">★</div>
                </div>

                {/* Simulated Manuscript lines */}
                <div className="flex flex-col gap-2.5 my-auto py-2 opacity-85 relative">
                  <div className="h-2 bg-current opacity-25 rounded-full w-3/4"></div>
                  <div className="h-2 bg-current opacity-20 rounded-full w-full"></div>
                  <div className="h-2 bg-current opacity-25 rounded-full w-5/6"></div>
                  <div className="h-2 bg-current opacity-20 rounded-full w-2/3"></div>
                  <div className="h-2.5 bg-current opacity-30 rounded-full w-11/12 my-1"></div>
                  <div className="h-2 bg-current opacity-20 rounded-full w-4/5"></div>
                  <div className="h-2 bg-current opacity-25 rounded-full w-full"></div>

                  {/* Highlighted Detected Regions */}
                  <div className="absolute top-0 left-0 right-1/4 h-8 border-2 border-primary bg-primary/15 rounded-md flex items-center px-1.5 shadow-sm">
                     <span className="text-[9px] font-bold bg-primary text-on-dark rounded-full w-4 h-4 flex items-center justify-center">1</span>
                  </div>
                  <div className="absolute top-10 left-0 right-0 h-10 border-2 border-primary bg-primary/15 rounded-md flex items-center px-1.5 shadow-sm">
                     <span className="text-[9px] font-bold bg-primary text-on-dark rounded-full w-4 h-4 flex items-center justify-center">2</span>
                  </div>
                  <div className="absolute top-24 left-0 right-1/3 h-8 border-2 border-primary/60 bg-primary/10 rounded-md flex items-center px-1.5">
                     <span className="text-[9px] font-bold bg-primary/80 text-on-dark rounded-full w-4 h-4 flex items-center justify-center">3</span>
                  </div>
                </div>

                <div className="flex justify-between items-center text-[9px] sm:text-[10px] opacity-40 font-mono pt-1 border-t border-black/5 dark:border-white/5">
                  <span>DETECTED LINES: 3</span>
                  <span>CONFIDENCE: 98%</span>
                </div>
             </div>
           </div>
        </div>
        
        {/* Tools Panel */}
        <div className="w-full md:w-72 lg:w-80 flex flex-col gap-3">
          <div className="glass-surface p-3.5 md:p-6 rounded-2xl md:rounded-[32px] flex flex-col gap-3">
            <h3 className="font-medium text-xs md:text-sm opacity-60 px-1 hidden md:block">{t('regionTools')}</h3>
            
            <div className="grid grid-cols-2 md:flex md:flex-col gap-2 md:gap-3">
              <AnimatedButton className="control flex items-center gap-2 justify-center py-2.5 px-3 text-xs md:text-sm rounded-xl md:rounded-[20px]">
                <Plus className="w-3.5 h-3.5 md:w-4 md:h-4 shrink-0"/> {t('addRegion')}
              </AnimatedButton>
              <AnimatedButton className="control flex items-center gap-2 justify-center py-2.5 px-3 text-xs md:text-sm rounded-xl md:rounded-[20px]">
                <Trash2 className="w-3.5 h-3.5 md:w-4 md:h-4 shrink-0"/> {t('deleteRegion')}
              </AnimatedButton>
              <AnimatedButton className="control flex items-center gap-2 justify-center py-2.5 px-3 text-xs md:text-sm rounded-xl md:rounded-[20px]">
                <Move className="w-3.5 h-3.5 md:w-4 md:h-4 shrink-0"/> {t('moveRegion')}
              </AnimatedButton>
              <AnimatedButton className="control flex items-center gap-2 justify-center py-2.5 px-3 text-xs md:text-sm rounded-xl md:rounded-[20px]">
                <Type className="w-3.5 h-3.5 md:w-4 md:h-4 shrink-0"/> {t('changeOrder')}
              </AnimatedButton>
            </div>
          </div>
        </div>
      </div>
    </Reveal>
  );
}

