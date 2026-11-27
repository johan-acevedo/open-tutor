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
  'topmenu.inboxEmpty': 'Ingen läxa skickad än',
  'topmenu.inboxOne': '{count} läxa skickad',
  'topmenu.inboxMany': '{count} läxor skickade',
  'topmenu.dropHint': 'Du kan också dra in en bild eller pdf i fönstret.',
  'topmenu.photo': 'Fota läxan',
  'topmenu.chooseImage': 'Välj bild',
  'topmenu.switchFallback': 'Byt elev',
  'topmenu.switchHint': 'Avslutar samtalet',
  'topmenu.aboutTitle': 'Om Talarum',
  'topmenu.aboutBy': 'Gjord av Johan Acevedo.',
  'topmenu.privacyLink': 'Läs om integritet',

  // Start menu (pre-call)
  'startmenu.about': 'Om Talarum',
  'startmenu.aboutText': 'Talarum är ett experiment: en AI du pratar med om läxan. Den förklarar och ritar på tavlan medan du själv löser uppgiften. Gratis än så länge.',
  'startmenu.privacy': 'Integritet',
  'startmenu.privacyText': 'Förnamn, årskurs och korta anteckningar sparas lokalt i den här webbläsaren. När ett samtal börjar skickas de med så att samtalet kan fortsätta där ni slutade.',
  'startmenu.privacyLink': 'Läs om integritet',

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
  'end.idle': 'Samtalet avslutades eftersom det var tyst en stund.',
  'end.topicLabel': 'Det här pratade vi om:',
  'end.clickedLabel': 'Det här klickade:',
  'end.nextLabel': 'Nästa gång:',
  'end.back': 'Tillbaka till start',
  'end.shareTitleYoung': 'Tipsa andra föräldrar',
  'end.shareTitleOld': 'Tipsa någon',
  'end.shareText': 'Känner du någon som också kämpar med läxan? Talarum är gratis än så länge.',
  'end.shareButton': 'Tipsa',
  'end.shareCopied': 'Kopierat ✓',

  // Household picker (siblings on one device)
  'picker.title': 'Vem ska prata?',
  'picker.new': '+ Någon ny',
  'picker.newHint': 'Börja utan sparad profil',
  'picker.back': 'Tillbaka',
  'picker.withCompanion': '{name} · {companion}',

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

  // Band copy (per-band companion and start page)
  'band.primary.companionName': 'Räven',
  'band.primary.welcomeBubble': 'Hej!',
  'band.primary.returningBubble': 'Hej {name}!',
  'band.primary.notYou': 'Inte {name}?',
  'band.primary.startButton': 'Prata med Räven',
  'band.primary.switchStudent': 'Byt elev',
  'band.middle.companionName': 'Lodjuret',
  'band.middle.welcomeBubble': 'Hej!',
  'band.middle.returningBubble': 'Hej {name}!',
  'band.middle.notYou': 'Inte {name}?',
  'band.middle.startButton': 'Prata med Lodjuret',
  'band.middle.switchStudent': 'Byt elev',
  'band.upper.companionName': 'Björnen',
  'band.upper.welcomeBubble': 'Hej!',
  'band.upper.returningBubble': 'Hej {name}!',
  'band.upper.notYou': 'Inte {name}?',
  'band.upper.startButton': 'Prata med Björnen',
  'band.upper.switchStudent': 'Byt person',

  // Landing pages (warm paper, 2026-11-27): / speaks to grundskola
  // families, /gymnasiet to upper-secondary students and adults.
  'landing.navLabel': 'Navigering',
  'landing.navPrice': 'Pris',
  'landing.headerPrivacy': 'Integritet',
  'landing.familyTitlePrefix': 'En lugn läxkompis som ',
  'landing.familyTitleAccent': 'pratar',
  'landing.familyTitleSuffix': '\u00a0– och visar.',
  'landing.familyIntro': 'Ditt barn säger vad det kör fast på. Talarum lyssnar, förklarar på svenska och skriver upp stegen på en tavla. Barnet räknar själv – Talarum ser till att det kommer vidare.',
  'landing.middleTitlePrefix': 'Plugga med någon som ',
  'landing.middleTitleAccent': 'lyssnar',
  'landing.middleTitleSuffix': '\u00a0– och visar.',
  'landing.upperTitlePrefix': 'Lugnt studiestöd du kan ',
  'landing.upperTitleAccent': 'prata',
  'landing.upperTitleSuffix': ' med.',
  'landing.introPrimary': 'Räven är för dig som går i åk 1–6. Säg vad du kör fast på, så förklarar Räven på svenska och skriver upp stegen på tavlan. Du räknar själv.',
  'landing.introMiddle': 'Lodjuret är för dig på högstadiet. Berätta var du kör fast, så frågar Lodjuret hur du tänkte, förklarar rakt och skriver upp stegen på tavlan. Lösningen blir din egen.',
  'landing.introUpper': 'Svåra uppgifter, prov och tentor – i din egen takt. Berätta hur du tänker, så går Björnen igenom det med dig steg för steg på tavlan. Arbetet förblir ditt eget.',
  'landing.switchLabel': 'Välj årskurs',
  'landing.audiencePrimary': 'Åk 1–6',
  'landing.audienceMiddle': 'Högstadiet',
  'landing.freeNow': 'Gratis medan vi testar.',
  'landing.plannedPrice': 'Planerat pris: 2\u00a0tim/vecka gratis, sedan 25\u00a0kr/tim. Ingen prenumeration.',
  'landing.listenAria': '{greeting} Lyssna på {companion}',
  'landing.listenTitle': 'Lyssna på {companion}',
  // The squared exercise book in the hero (illustrative examples).
  'landing.bookLive': 'Tavlan, just nu',
  'landing.saidBy': '{companion}:',
  'landing.bookSubjectPrimary': 'Matte · åk 3',
  'landing.bookTaskPrimary': 'Uppgift 7',
  'landing.bookQuestionPrimary': 'Hur mycket är 36 + 47?',
  'landing.row1Primary': '30 + 40 = 70',
  'landing.row2Primary': '6 + 7 = 13',
  'landing.row3Primary': '70 + 13 = 83',
  'landing.note1Primary': 'tiotal',
  'landing.note2Primary': 'ental',
  'landing.bookSaidPrimary': 'Du räknade tiotalen först. Hur gjorde du med sexan och sjuan?',
  'landing.bookSubjectMiddle': 'Matte · åk 8',
  'landing.bookTaskMiddle': 'Uppgift 4',
  'landing.bookQuestionMiddle': 'Lös ekvationen 3x\u00a0+\u00a05\u00a0=\u00a020.',
  'landing.row1Middle': '3x + 5 = 20',
  'landing.row2Middle': '3x = 15',
  'landing.row3Middle': 'x = 5',
  'landing.note1Middle': '',
  'landing.note2Middle': '−5 på båda sidor',
  'landing.bookSaidMiddle': 'Snyggt. Hur kan du kolla att x\u00a0=\u00a05 stämmer?',
  'landing.bookSubjectUpper': 'Matematik 3c',
  'landing.bookTaskUpper': 'Uppgift 12',
  'landing.bookQuestionUpper': 'Derivera f(x)\u00a0=\u00a0x²\u00a0+\u00a03x och beräkna f′(2).',
  'landing.row1Upper': 'f(x) = x² + 3x',
  'landing.row2Upper': 'f′(x) = 2x + 3',
  'landing.row3Upper': 'f′(2) = 7',
  'landing.note1Upper': '',
  'landing.note2Upper': 'term för term',
  'landing.bookSaidUpper': 'Stämmer. Vad säger f′(2)\u00a0=\u00a07 om grafen när x\u00a0=\u00a02?',
  // Planned price (billing is not live: say so plainly).
  'landing.priceKicker': 'Planerat pris',
  'landing.priceTitleFamily': 'Betala bara för tiden ni pratar.',
  'landing.priceTitleAdult': 'Betala bara för tiden du pratar.',
  'landing.priceSub': 'Ingen prenumeration att komma ihåg att säga upp. Så här är det tänkt när testperioden är slut.',
  'landing.priceFreeLabel': 'De första 2 timmarna',
  'landing.priceFreeNote': 'varje vecka',
  'landing.priceFreeValue': '0 kr',
  'landing.priceAfterLabel': 'Därefter',
  'landing.priceAfterNote': 'per samtalstimme',
  'landing.priceAfterValue': '25 kr/tim',
  'landing.priceSubscriptionLabel': 'Prenumeration och bindningstid',
  'landing.priceSubscriptionValue': 'Ingen',
  'landing.priceNow': 'Just nu helt gratis under testperioden – inget konto och inget kort behövs.',
  'landing.versusTitleFamily': 'En timmes läxhjälp kostar',
  'landing.versusTitleAdult': 'En timmes studiehjälp kostar',
  'landing.versusUs': 'Talarum, planerat',
  'landing.versusUsValue': '25 kr',
  'landing.versusHuman': 'Mänsklig läxhjälp',
  'landing.versusHumanAdult': 'Privatlärare',
  'landing.versusHumanValue': '300–500 kr',
  'landing.versusNoteFamily': 'En lärare som känner ditt barn kan mer än vi. Talarum är till för vardagskvällarna däremellan – när läxan ska in i morgon och ingen hemma minns hur man delar bråk.',
  'landing.versusNoteAdult': 'En lärare som känner dig kan mer än vi. Talarum är till för kvällarna däremellan – när provet närmar sig och du vill gå igenom en uppgift till.',
  // Steps
  'landing.howTitle': 'Så går det till',
  'landing.howHeadFamily': 'Det barnet hör syns samtidigt på tavlan.',
  'landing.howHeadAdult': 'Det du hör syns samtidigt på tavlan.',
  'landing.stepN': 'Steg {n}',
  'landing.step1Title': 'Visa läxan',
  'landing.step1TitleAdult': 'Visa uppgiften',
  'landing.step1Text': 'Fota uppgiften eller läs upp den. Den hamnar överst på tavlan.',
  'landing.step2Title': 'Prata om uppgiften',
  'landing.step2Text': '{companion} frågar först hur du tänker och väntar på svaret. Förklarar rakt när det behövs.',
  'landing.step3Title': 'Lös den ihop',
  'landing.step3Text': 'Stegen hamnar på tavlan medan du räknar själv. Svaret blir ditt eget.',
  // Quiet cross-links above the footer
  'landing.crossLabel': 'Andra åldrar',
  'landing.crossUpperLead': 'Pluggar du på gymnasiet eller som vuxen?',
  'landing.crossUpperLink': 'Studiestöd med Björnen',
  'landing.crossFamilyLead': 'Yngre syskon hemma?',
  'landing.crossFamilyLink': 'Läxhjälp för åk 1–9',
  'landing.crossMiddleLead': 'Går du på högstadiet?',
  'landing.crossMiddleLink': 'Läxhjälp med Lodjuret',
  'landing.crossPrimaryLead': 'Går du i åk 1–6?',
  'landing.crossPrimaryLink': 'Läxhjälp med Räven',
  // Footer
  'landing.footerText': 'Talarum är ett experiment av Johan Acevedo. Inget konto – förnamn och anteckningar sparas lokalt i din webbläsare.',
  'landing.footerPrivacy': 'Integritet',

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
  // Brand
  'brand.name': 'Talarum',

  // Privacy page (/integritet): principles, not a vendor list.
  'privacy.kicker': 'Integritet',
  'privacy.title': 'Om Talarum och din integritet',
  'privacy.intro': 'Talarum är läxhjälp och studiestöd du pratar med på svenska – skapat av Johan Acevedo som ett experiment. Inget konto behövs för att börja.',
  'privacy.browserTitle': 'Det som stannar i webbläsaren',
  'privacy.browserBody': 'Förnamn, årskurs och korta anteckningar från tidigare samtal sparas bara lokalt i webbläsaren (tillsammans med ett slumpmässigt webbläsarnummer). Rensar du webbplatsdata försvinner allt lokalt. När ett samtal börjar skickas uppgifterna med, så att samtalet kan fortsätta där ni slutade.',
  'privacy.sendTitle': 'Det som skickas under samtalet',
  'privacy.sendBody': 'För att kunna lyssna, svara och rita förklaringar använder Talarum externa röst- och AI-tjänster. För att kunna hålla tjänsten billig kan vissa av de AI-tjänster vi använder idag använda samtalstext för att förbättra sina modeller.',
  'privacy.statsTitle': 'Statistik och reklam',
  'privacy.statsBody': 'Ingen reklam och inga namn i vår statistik. Vi samlar bara in enkel, anonym användnings- och felstatistik inom EU för att se om tjänsten fungerar.',
  'privacy.contactTitle': 'Kontakt',
  'privacy.contactPrefix': 'Frågor? Skriv till',
  'privacy.contactEmail': 'hej@talarum.se',
  'privacy.back': 'Tillbaka',
  'privacy.backHome': 'Tillbaka till start',

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
