'use client';
import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';
export function Button({className,...props}:React.ButtonHTMLAttributes<HTMLButtonElement>){return <button className={twMerge(clsx('button',className))} {...props}/>}
export function Modal({title,children,onClose}:{title:string;children:React.ReactNode;onClose:()=>void}){return <Dialog.Root open onOpenChange={open=>!open&&onClose()}><Dialog.Portal><Dialog.Overlay className="overlay"/><Dialog.Content className="modal"><Dialog.Title className="text-2xl font-semibold pr-10">{title}</Dialog.Title><Dialog.Description className="sr-only">Review the information and available actions.</Dialog.Description><Dialog.Close asChild><button className="close" aria-label="Close"><X size={20}/></button></Dialog.Close>{children}</Dialog.Content></Dialog.Portal></Dialog.Root>}
