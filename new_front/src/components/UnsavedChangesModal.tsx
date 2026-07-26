import React from 'react';
import { AnimatedButton } from './Animations';

interface UnsavedChangesModalProps {
  isOpen: boolean;
  onSaveAndLeave: () => void;
  onLeaveWithoutSaving: () => void;
  onStay: () => void;
}

export function UnsavedChangesModal({ isOpen, onSaveAndLeave, onLeaveWithoutSaving, onStay }: UnsavedChangesModalProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="bg-white dark:bg-ink rounded-3xl p-8 max-w-md w-full shadow-2xl border border-black/10 dark:border-white/10 animate-fade-in-up">
        <h3 className="text-xl font-medium mb-2">Unsaved changes</h3>
        <p className="opacity-60 mb-8 text-sm">You have unsaved changes. Do you want to save them before leaving?</p>
        
        <div className="flex flex-col gap-3">
          <AnimatedButton onClick={onSaveAndLeave} className="button-primary w-full justify-center">
            Save and leave
          </AnimatedButton>
          <AnimatedButton onClick={onLeaveWithoutSaving} className="button-secondary w-full justify-center text-red-600 dark:text-red-400 !border-red-500/20 hover:!bg-red-500/10">
            Leave without saving
          </AnimatedButton>
          <AnimatedButton onClick={onStay} className="button-secondary w-full justify-center">
            Stay
          </AnimatedButton>
        </div>
      </div>
    </div>
  );
}
