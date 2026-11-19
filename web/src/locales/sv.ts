// Swedish catalogue: the only place user-visible Swedish lives in web/src.
// Every other .ts/.tsx file looks strings up by key, so adding a second
// language later means adding one more file with the same keys.
// Missing keys are a compile error (SvKey), and the guard test fails on any
// Swedish-looking literal outside locales/ and *.test.* files.

export const localeId = 'sv' as const;
export const htmlLang = 'sv' as const;

export const sv = {
  // App shell
  'app.connecting': 'Ansluter till tutorn…',
  'app.micBlockedText': 'Jag hör dig inte just nu. Du kan skriva här under.',
  'app.retry': 'Försök igen',
  'app.resumeContinue': 'Fortsätt samtalet',
  'app.resumeListen': 'Tryck för att höra mig',
  'app.reconnecting': 'Tappade kontakten – försöker igen…',
  'app.disconnected': 'Tappade kontakten.',
  'app.restart': 'Starta igen',
  'app.ending': 'Avslutar samtalet…',
  'app.endButton': 'Avsluta',
  'app.endButtonAria': 'Avsluta sessionen',
  'app.cameraInputAria': 'Fota läxan',
  'app.youPrefix': 'Du:',

  // Avatar / status pill
  'avatar.tutorLabel': 'Tutorn',
  'pill.speaking': 'Pratar',
  'pill.waiting': 'Jag väntar',
  'pill.watching': 'Väntar medan du tittar',
  'pill.drawing': 'Ritar…',
  'pill.thinking': 'Tänker…',
  'pill.textWaiting': 'Väntar på text',
  'pill.listening': 'Lyssnar',
  'pill.hello': 'Hej!',

  // Board
  'board.navLabel': 'Bläddra i tavlan',
  'board.back': '← Tillbaka',
  'board.forward': 'Framåt →',
  'board.emptyGreeting': 'Hej{name}!',
  'board.emptyBody': 'Här hamnar det vi jobbar med.',
  'board.emptyHint': 'Säg hej — tutorn ritar upp här.',

  // Bottom bar
  'bottombar.controlsLabel': 'Samtalskontroller',
  'bottombar.attachAria': 'Lägg till läxa — välj fil',
  'bottombar.attachTitle': 'Lägg till läxa',
  'bottombar.inputPlaceholder': 'Skriv här om du vill…',
  'bottombar.inputAria': 'Skriv här om du vill',
  'bottombar.send': 'Skicka',
  'bottombar.micBlocked': 'Mikrofon blockerad',
  'bottombar.micOff': 'Stäng av mikrofonen',
  'bottombar.micOn': 'Mikrofon av — sätt på mikrofonen',
  'bottombar.micOnTitle': 'Mikrofon på',
  'bottombar.micOffTitle': 'Mikrofon av',

  // Top menu (in-call)
  'topmenu.menuLabel': 'Meny',
  'topmenu.inboxLabel': 'Inkorg för läxor',
  'topmenu.inboxEmpty': 'Inkorg · tom',
  'topmenu.inboxOne': 'Inkorg · {count} uppgift',
  'topmenu.inboxMany': 'Inkorg · {count} uppgifter',
  'topmenu.dropHint': 'släpp fil här',
  'topmenu.photo': 'Fota läxan',
  'topmenu.chooseImage': 'Välj bild',
  'topmenu.switchFallback': 'Byt elev',
  'topmenu.aboutTitle': 'Om Open Tutor',
  'topmenu.aboutBy': 'by Johan Acevedo',
  'topmenu.close': 'Stäng',

  // Start menu (pre-call)
  'startmenu.about': 'Om tjänsten',
  'startmenu.aboutText': 'Open Tutor är en rösttutor som hjälper dig med läxor och skolarbete. Du pratar, och tutorn förklarar och visar på skärmen.',
  'startmenu.privacy': 'Integritet',
  'startmenu.privacyText': 'Din profil och anteckningar sparas bara i den här webbläsaren. Röstsamtalet går via våra leverantörer så att tutorn kan höra dig. Inget konto behövs.',

  // Homework tray
  'tray.label': 'Lägg till läxa',
  'tray.pickerTitle': 'Visa mig din läxa',
  'tray.readyTitle': 'Redo att skicka?',
  'tray.previewAlt': 'Förhandsvisning av läxan',
  'tray.photo': 'Fota läxan',
  'tray.retake': 'Ta om foto',
  'tray.choose': 'Välj bild eller PDF',
  'tray.cancel': 'Avbryt',
  'tray.sending': 'Skickar…',
  'tray.send': 'Skicka till tutorn',
  'tray.hint': 'Kontrollera att texten går att läsa innan du skickar.',
  'tray.remove': 'Ta bort',
  'tray.removeAria': 'Ta bort {name}',
  'tray.fallbackName': 'Foto',
  'tray.fallbackImageTitle': 'Bild',
  'tray.fallbackImageSource': 'bild',
  'tray.fallbackPdfTitle': 'PDF',
  'tray.fallbackPdfSource': 'pdf',
  'tray.pastedTitle': 'Inklistrad text',

  // End card
  'end.greetingNamed': 'Bra jobbat idag, {name}!',
  'end.greetingAnon': 'Bra jobbat idag!',
  'end.topicLabel': 'Det här pratade vi om:',
  'end.clickedLabel': 'Det här klickade:',
  'end.nextLabel': 'Nästa gång:',
  'end.back': 'Tillbaka till start',

  // Cards (resources, homework, pending)
  'cards.drawing': 'Ritar…',
  'cards.sourcePrefix': 'Källa:',
  'cards.openNewTab': 'Öppna i ny flik',
  'cards.thinkAboutPrefix': 'Fundera på:',
  'cards.submittedAlt': 'Inlämnad bild {n}',
  'cards.doneTalk': 'Klar – prata vidare',

  // Phone fox strip / hero
  'fox.showPage': 'Visa sidan',
  'fox.showPageWithTitle': 'Visa sidan: {title}',
  'fox.showCompanion': 'Visa {name}',

  // Welcome (voice-first start)
  'welcome.starting': 'Startar…',
  'welcome.voiceNote': 'Prata om läxan med rösten — tutorn frågar vad du heter. Mikrofonen sätts på när du startar. Allt sparas bara i den här webbläsaren.',

  // Band copy (per-band companion and start page)
  'band.primary.companionName': 'Räven',
  'band.primary.welcomeBubble': 'Hej! Ska vi prata?',
  'band.primary.returningBubble': 'Hej {name}! Ska vi köra?',
  'band.primary.notYou': 'Inte {name}? Byt',
  'band.primary.startButton': 'Prata med Räven',
  'band.primary.switchStudent': 'Byt elev',
  'band.middle.companionName': 'Lodjuret',
  'band.middle.welcomeBubble': 'Hej! Ska vi prata?',
  'band.middle.returningBubble': 'Hej {name}! Ska vi köra?',
  'band.middle.notYou': 'Inte {name}? Byt',
  'band.middle.startButton': 'Prata med Lodjuret',
  'band.middle.switchStudent': 'Byt elev',
  'band.upper.companionName': 'Björnen',
  'band.upper.welcomeBubble': 'Hej! Ska vi prata?',
  'band.upper.returningBubble': 'Hej {name}! Ska vi köra?',
  'band.upper.notYou': 'Inte {name}? Byt',
  'band.upper.startButton': 'Prata med Björnen',
  'band.upper.switchStudent': 'Byt person',

  // Toasts (session errors)
  'toast.full': 'Det är fullt just nu. Försök igen om en stund.',
  'toast.startFailed': 'Kunde inte starta sessionen. Kontrollera anslutningen och försök igen.',
  'toast.connectFailed': 'Kunde inte ansluta till samtalet. Försök igen.',
  'toast.sendFailed': 'Kunde inte skicka meddelandet. Försök igen.',
  'toast.notifyFailed': 'Kunde inte meddela tutorn. Försök igen.',
  'toast.imageFailed': 'Bilden kunde inte läsas eller skickas. Prova JPG, PNG eller PDF och kontrollera anslutningen.',
  'toast.pdfFailed': 'Kunde inte läsa PDF:en. Prova en annan fil.',
  'toast.pdfEmpty': 'PDF:en verkar vara tom.',
  'toast.textFailed': 'Kunde inte skicka texten. Försök igen.',
  'toast.fileType': 'Den filtypen stöds inte ännu. Prova PDF, PNG eller JPG.',
  'toast.allFailed': 'Alla filer kunde inte skickas. Prova JPG, PNG eller PDF.',

  // Smart Screen shell (injected into the frame; shell.js has no Swedish of its own)
  'shell.send': 'Skicka',
  'shell.sent': 'Skickat ✓',
  'shell.answerLabel': 'Ditt svar',
  'shell.gapLabel': 'Lucka',
  'shell.loading': 'Laddar {topic} …',
  'shell.bc': 'f.Kr.',
  'shell.ad': 'e.Kr.',
  'shell.mapCreditHistorical': 'Gränser: historical-basemaps · Natural Earth',
  'shell.mapCredit': 'Natural Earth',

  // Dev demo (screen-demo=1) and design review: example lesson content
  'demo.klockanTitle': 'Vad är klockan?',
  'demo.divisionTitle': 'Pris per kilo',
  'demo.longLine': 'Titta på klockan på sidan. Den stora visaren pekar på tolv, och den lilla står på tre. Då är klockan tre, eller hur? Säg vad du tror att den lilla visaren betyder.',
  'demo.greeting': 'Hej! Jag heter {companion}. Vad jobbar du med idag?',
  'demo.answersLabel': 'Svar från barnet',
  'demo.showPatch': 'Visa patch',
  'demo.reveal': 'Avslöja',
  'demo.point': 'Peka',
  'demo.header': 'Skärm-demo',
  'review.exampleTitle': 'Enheter och samband',
  'review.exampleBody': '<h1>Enheter och samband</h1><div class="card"><p class="big">sträcka = hastighet × tid</p></div><p>Vilken enhet mäter sträcka?</p><ot-answer id="unit" label="Ditt svar"></ot-answer>',
  'review.exampleCaption': 'Vi börjar med vad vi vet.',
  'review.preparing': 'Förbereder tavlan',
} as const;

export type SvKey = keyof typeof sv;

export function t(key: SvKey, vars?: Record<string, string | number>): string {
  let out: string = sv[key];
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      out = out.replace(`{${k}}`, String(v));
    }
  }
  return out;
}
