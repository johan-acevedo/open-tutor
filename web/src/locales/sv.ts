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
  'band.middle.companionName': 'Linnea',
  'band.middle.welcomeBubble': 'Hej!',
  'band.middle.returningBubble': 'Hej {name}!',
  'band.middle.notYou': 'Inte {name}?',
  'band.middle.startButton': 'Prata med Linnea',
  'band.middle.switchStudent': 'Byt elev',
  'band.upper.companionName': 'Björnen',
  'band.upper.welcomeBubble': 'Hej!',
  'band.upper.returningBubble': 'Hej {name}!',
  'band.upper.notYou': 'Inte {name}?',
  'band.upper.startButton': 'Prata med Björnen',
  'band.upper.switchStudent': 'Byt person',

  // Landing pages (warm paper v4, 2026-11-27). One voice per page:
  // / and /ak1-6 speak to parents about "barnet"; /hogstadiet speaks to the
  // student directly ("du"); /gymnasiet speaks to upper-secondary students
  // and adults ("du", studiestöd).
  'landing.navLabel': 'Skolnivå',
  'landing.navPrimary': 'Åk 1–6',
  'landing.navMiddle': 'Högstadiet',
  'landing.navUpper': 'Gymnasiet',
  'landing.headerPrivacy': 'Integritet',
  'landing.titlePrefixPrimary': 'En lugn läxhjälp som ',
  'landing.titleAccentPrimary': 'pratar',
  'landing.titleSuffixPrimary': ' – och visar.',
  'landing.titlePrefixMiddle': 'En lugn läxhjälp du kan ',
  'landing.titleAccentMiddle': 'prata',
  'landing.titleSuffixMiddle': ' med.',
  'landing.titlePrefixUpper': 'Lugnt studiestöd du kan ',
  'landing.titleAccentUpper': 'prata',
  'landing.titleSuffixUpper': ' med.',
  'landing.introPrimary': 'Ditt barn säger vad det kör fast på. Talarum lyssnar, förklarar på svenska och ritar upp stegen på en tavla – medan barnet själv räknar vidare.',
  'landing.introMiddle': 'Säg vad du kört fast på. Linnea lyssnar, förklarar på svenska och ritar upp stegen på tavlan – medan du själv räknar vidare.',
  'landing.introUpper': 'Svåra uppgifter, prov och tentor – i din egen takt. Berätta hur du tänker, så går Björnen igenom det med dig steg för steg på tavlan. Arbetet förblir ditt eget.',
  'landing.quietFree': 'Gratis medan vi testar',
  'landing.quietAccount': 'Inget konto',
  'landing.listen': 'Hör rösten',
  'landing.listenPlaying': 'Spelar…',
  'landing.listenSuffix': ' – {companion}',
  'landing.listenTitle': 'Lyssna på {companion}',
  // The hero's squared exercise book: work in progress, never the answer.
  'landing.showcaseLabel': 'Exempel: {companion} går igenom en uppgift',
  'landing.callLabel': '{companion} i samtalet',
  'landing.learnerPrimary': 'Barnet',
  'landing.learnerYou': 'Du',
  'landing.bookSubjectPrimary': 'Matte · åk 3',
  'landing.bookTaskPrimary': 'Uppgift 7',
  'landing.bookQuestionPrimary': 'Hur mycket är 36 + 47?',
  'landing.row1Primary': '30 + 40 = 70',
  'landing.note1Primary': 'tiotal',
  'landing.row2Primary': '6 + 7 = ?',
  'landing.learnerSaidPrimary': 'Jag började med 30 plus 40.',
  'landing.companionSaidPrimary': 'Snyggt! Vad blir 6 plus 7 då?',
  'landing.bookSubjectMiddle': 'Matte · åk 8',
  'landing.bookTaskMiddle': 'Uppgift 4',
  'landing.bookQuestionMiddle': 'Lös ekvationen 3x + 5 = 20.',
  'landing.row1Middle': '3x = 15',
  'landing.note1Middle': '−5 på båda sidor',
  'landing.row2Middle': 'x = ?',
  'landing.learnerSaidMiddle': 'Jag tar minus 5 på båda sidor.',
  'landing.companionSaidMiddle': 'Precis! Vad gör du med trean framför x?',
  'landing.bookSubjectUpper': 'Matematik 3c',
  'landing.bookTaskUpper': 'Uppgift 12',
  'landing.bookQuestionUpper': 'Derivera f(x) = x² + 3x och beräkna f′(2).',
  'landing.row1Upper': 'f′(x) = 2x + 3',
  'landing.note1Upper': 'term för term',
  'landing.row2Upper': 'f′(2) = ?',
  'landing.learnerSaidUpper': 'Derivatan blir 2x plus 3.',
  'landing.companionSaidUpper': 'Stämmer. Vad får du när x = 2?',
  // Så går det till
  'landing.howKicker': 'Så går det till',
  'landing.howHeadPrimary': 'Så hjälper Talarum barnet framåt.',
  'landing.howHeadYou': 'Så hjälper Talarum dig framåt.',
  'landing.stepN': '{n}.',
  'landing.step1Title': 'Fota eller säg uppgiften',
  'landing.step1TextPrimary': 'Barnet fotar läxan eller läser upp den högt, så hamnar den direkt på tavlan.',
  'landing.step1TextYou': 'Ta en bild på uppgiften eller läs upp den högt, så hamnar den direkt på tavlan.',
  'landing.step2Title': 'Prata och se förklaringen',
  'landing.step2TextPrimary': '{companion} lyssnar, frågar hur barnet tänker och visar stegen utan att ge bort svaret.',
  'landing.step2TextYou': '{companion} lyssnar, frågar hur du tänker och visar stegen utan att ge bort svaret.',
  'landing.step3TitlePrimary': 'Barnet löser själv',
  'landing.step3TitleYou': 'Du löser själv',
  'landing.step3TextPrimary': 'Barnet räknar ut sista steget på egen hand och förstår varför.',
  'landing.step3TextYou': 'Du räknar ut sista steget på egen hand och förstår varför.',
  'landing.stepProblemPrimary': '36 + 47',
  'landing.stepProblemMiddle': '3x + 5 = 20',
  'landing.stepProblemUpper': 'f(x) = x² + 3x',
  'landing.stepDonePrimary': '70 + 13\n= 83',
  'landing.stepDoneMiddle': 'x = 5',
  'landing.stepDoneUpper': 'f′(2) = 7',
  // Planerat pris
  'landing.priceKicker': 'Planerat pris',
  'landing.priceTitle': 'Gratis medan vi testar.',
  'landing.priceNowLabel': 'Nu',
  'landing.priceNowValue': '0 kr',
  'landing.priceLaterLabel': 'Planerat senare',
  'landing.priceLaterValue': '2 tim/vecka gratis, sedan 25 kr/tim',
  'landing.priceTermLabel': 'Bindningstid',
  'landing.priceTermValue': 'Ingen prenumeration',
  'landing.versusLabel': 'Pris per timme jämfört med privat hjälp',
  'landing.versusUs': 'Talarum, planerat',
  'landing.versusUsValue': '25 kr/tim',
  'landing.versusHuman': 'Privat läxhjälp',
  'landing.versusHumanUpper': 'Privatlärare',
  'landing.versusHumanValue': '300–500 kr/tim',
  'landing.versusNotePrimary': 'Betala bara för tiden ni pratar – för vardagskvällarna när läxan ska in.',
  'landing.versusNoteMiddle': 'Betala bara för tiden du pratar – för kvällarna när läxan ska in i morgon.',
  'landing.versusNoteUpper': 'Betala bara för tiden du pratar – för kvällarna när provet närmar sig.',
  // Closing call to action
  'landing.closingPrimary': 'Redo att testa på kvällens läxa?',
  'landing.closingYou': 'Redo att testa på nästa uppgift?',
  // Footer
  'landing.footerText': 'Ett svenskt experiment av Johan Acevedo. Inget konto krävs – läs hur samtal och uppgifter hanteras.',
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
