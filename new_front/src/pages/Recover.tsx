import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from '../lib/i18n';
import { Reveal, AnimatedButton } from '../components/Animations';
import { motion } from 'motion/react';

const MotionLink = motion.create(Link);

export function Recover() {
  const { t } = useTranslation();
  const [sent, setSent] = useState(false);
  
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setSent(true);
  };
  
  return (
    <Reveal className="min-h-[80vh] flex items-center justify-center p-4">
      <div className="glass-surface p-10 md:p-14 rounded-[32px] w-full max-w-md">
        <h1 className="text-3xl font-light tracking-tight mb-8">{t('forgotPassword')}</h1>
        {!sent ? (
          <form onSubmit={handleSubmit} className="flex flex-col gap-6">
            <input type="email" placeholder={t('email')} required className="control w-full" />
            <AnimatedButton type="submit" className="button-primary w-full mt-2">Recover</AnimatedButton>
            <div className="text-center mt-4">
              <Link to="/auth/sign-in" className="text-sm opacity-60 hover:opacity-100 transition-opacity">{t('cancel')}</Link>
            </div>
          </form>
        ) : (
          <div className="flex flex-col gap-6 text-center">
            <p className="opacity-80">Recovery email sent. Please check your inbox.</p>
            <MotionLink whileTap={{ scale: 0.96 }} to="/auth/sign-in" className="button-primary w-full mt-2 inline-flex justify-center items-center">{t('signIn')}</MotionLink>
          </div>
        )}
      </div>
    </Reveal>
  );
}
