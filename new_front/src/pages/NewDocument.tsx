import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../lib/i18n';
import { useAppStore } from '../lib/store';
import { UploadCloud, FileImage } from 'lucide-react';
import { Reveal, AnimatedButton } from '../components/Animations';
import { motion } from 'motion/react';

export function NewDocument() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addDocument = useAppStore(state => state.addDocument);
  const [file, setFile] = useState<File | null>(null);
  
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      setFile(e.dataTransfer.files[0]);
    }
  };

  const handleContinue = () => {
    if (!file) return;
    const newDocId = Math.random().toString(36).substring(7);
    addDocument({
      id: newDocId,
      name: file.name,
      status: 'draft',
      updatedAt: new Date().toISOString(),
      pageCount: 1,
      step: 'prepare'
    });
    navigate(`/documents/${newDocId}/pages/1/prepare`);
  };

  return (
    <Reveal className="flex flex-col gap-6 md:gap-10 max-w-2xl mx-auto items-center mt-2 md:mt-6 w-full">
      <h1 className="h2 text-center text-xl md:text-3xl font-light">{t('newDocument')}</h1>
      
      <motion.div 
        whileTap={{ scale: 0.98 }}
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleDrop}
        className="glass-surface w-full min-h-[250px] sm:min-h-[280px] md:aspect-video rounded-[28px] md:rounded-[40px] flex flex-col items-center justify-center p-6 md:p-12 text-center border-dashed border-2 border-black/10 dark:border-white/20 transition-all cursor-pointer relative overflow-hidden group shadow-sm hover:shadow-md"
      >
         <input 
           type="file" 
           accept="image/*" 
           className="absolute inset-0 opacity-0 cursor-pointer z-20" 
           onChange={(e) => {
             if (e.target.files && e.target.files[0]) setFile(e.target.files[0]);
           }} 
         />
         
         <div className="absolute inset-0 bg-white/0 group-hover:bg-white/5 transition-colors pointer-events-none" />

         {!file ? (
           <motion.div 
             initial={{ opacity: 0, scale: 0.95 }}
             animate={{ opacity: 1, scale: 1 }}
             className="relative z-10 flex flex-col items-center py-2"
           >
             <div className="w-14 h-14 md:w-20 md:h-20 rounded-full bg-black/5 dark:bg-white/5 flex items-center justify-center mb-3 md:mb-6">
                <UploadCloud className="w-6 h-6 md:w-8 md:h-8 opacity-40" />
             </div>
             <p className="text-base md:text-xl font-medium mb-1 md:mb-2">{t('dragAndDrop')}</p>
             <p className="text-xs md:text-sm opacity-60 px-4">{t('orChooseFile')}</p>
           </motion.div>
         ) : (
           <motion.div 
             initial={{ opacity: 0, scale: 0.95 }}
             animate={{ opacity: 1, scale: 1 }}
             className="relative z-10 flex flex-col items-center py-2 max-w-full px-4"
           >
             <div className="w-14 h-14 md:w-20 md:h-20 rounded-full bg-black/5 dark:bg-white/5 flex items-center justify-center mb-3 md:mb-6">
                <FileImage className="w-6 h-6 md:w-8 md:h-8 opacity-40" />
             </div>
             <p className="text-base md:text-xl font-medium mb-1 truncate max-w-xs">{file.name}</p>
             <p className="text-xs md:text-sm opacity-60 mb-4 md:mb-6">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
             <AnimatedButton className="button-secondary relative z-30 px-5 py-2 text-xs md:text-sm" onClick={(e) => { e.preventDefault(); setFile(null); }}>{t('replaceImage')}</AnimatedButton>
           </motion.div>
         )}
      </motion.div>
      
      <div className="flex gap-3 md:gap-4 w-full max-w-md">
         <AnimatedButton onClick={() => navigate(-1)} className="button-secondary flex-1 min-h-[48px] md:min-h-[52px]">{t('cancel')}</AnimatedButton>
         <AnimatedButton onClick={handleContinue} disabled={!file} className="button-primary flex-1 min-h-[48px] md:min-h-[52px] disabled:opacity-50 transition-opacity">{t('continue')}</AnimatedButton>
      </div>
    </Reveal>
  );
}
