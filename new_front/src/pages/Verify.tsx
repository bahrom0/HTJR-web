import { Link } from 'react-router-dom';
import { useTranslation } from '../lib/i18n';
import { Reveal } from '../components/Animations';
import { motion } from 'motion/react';

const MotionLink = motion.create(Link);

export function Verify() {
  const { t } = useTranslation();
  
  return (
    <Reveal className="min-h-[80vh] flex items-center justify-center p-4">
      <div className="glass-surface p-10 md:p-14 rounded-[32px] w-full max-w-md text-center">
        <h1 className="text-3xl font-light tracking-tight mb-6">Verify Email</h1>
        <p className="opacity-80 mb-8">We sent a verification link to your email. Please verify to continue.</p>
        <MotionLink whileTap={{ scale: 0.96 }} to="/auth/sign-in" className="button-primary w-full inline-flex justify-center items-center">{t('signIn')}</MotionLink>
      </div>
    </Reveal>
  );
}
