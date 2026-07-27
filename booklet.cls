%% booklet.cls
%% ---------------------------------------------------------------------
%% Minimal exam/booklet class used by the Exam Platform's LaTeX export
%% (latex_export.py). Provides the small set of question-authoring
%% commands the platform's "Create Question" form maps onto:
%%
%%   bookletquestions   environment wrapping the whole set of questions
%%   \tmarks{n}         mark label placed after ordinary text
%%   \emarks{n}         mark label placed after a formula/displayed equation
%%   subparts           vertical, indented (a)/(b)/(c) sub-question list
%%   tinysubparts       compact, inline (a) ... (b) ... sub-question list
%%   \breakquestion      "continued on next page" hint + page break
%%   solution           environment for model answers (see [shadedsolutions])
%%   \answerspace{len}  ruled blank space of height <len> for handwritten work
%%   \answerfill        fills the rest of the current page as blank space
%%
%% Class option:
%%   shadedsolutions    give `solution` a light grey shaded background
%%                      (otherwise it is a plain "Solution:" paragraph)
%% ---------------------------------------------------------------------

\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{booklet}[2026/07/27 v1.0 Exam Platform booklet class]

% -- Class options -------------------------------------------------------

\newif\ifbooklet@shaded
\booklet@shadedfalse
\DeclareOption{shadedsolutions}{\booklet@shadedtrue}

% Anything else (10pt, 11pt, 12pt, a4paper, ...) is forwarded to article.
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{article}}
\ProcessOptions\relax

\LoadClass{article}

% -- Packages --------------------------------------------------------------

\RequirePackage[a4paper, margin=2.5cm]{geometry}
\RequirePackage[utf8]{inputenc}
\RequirePackage{amsmath, amssymb}
\RequirePackage[inline]{enumitem}
\RequirePackage{xcolor}
\RequirePackage{framed}

\setlength{\parindent}{0pt}
\setlength{\parskip}{6pt}

% ---------------------------------------------------------------------
% bookletquestions: container environment for the whole set of questions
% on a paper. Doesn't change layout by itself today, but gives the
% question list a single addressable scope (e.g. for future numbering
% or spacing tweaks) and mirrors how questions are grouped conceptually.
% ---------------------------------------------------------------------
\newenvironment{bookletquestions}{%
  \par
}{%
  \par
}

% ---------------------------------------------------------------------
% \tmarks{n} / \emarks{n}: mark labels.
%   \tmarks -- follows ordinary descriptive text, spells out "marks".
%   \emarks -- follows a formula or displayed equation; kept short so it
%              reads naturally immediately after mathematics.
% ---------------------------------------------------------------------
\newcommand{\tmarks}[1]{\hfill\textbf{[#1 marks]}}
\newcommand{\emarks}[1]{\hfill\textbf{[#1]}}

% ---------------------------------------------------------------------
% subparts / tinysubparts: sub-question (a), (b), (c) ... lists.
%   subparts      -- standard vertical list, one sub-question per line.
%   tinysubparts  -- compact inline list, for short sub-questions that
%                    read naturally side by side.
% ---------------------------------------------------------------------
\newenvironment{subparts}{%
  \begin{enumerate}[label=(\alph*), leftmargin=2.2em, itemsep=6pt, topsep=4pt]
}{%
  \end{enumerate}
}

\newenvironment{tinysubparts}{%
  \begin{enumerate*}[label=(\alph*), itemjoin={\hspace{1.5em}}]
}{%
  \end{enumerate*}
}

% ---------------------------------------------------------------------
% \breakquestion: hint + page break for a question that is expected to
% (or does) span more than one page.
% ---------------------------------------------------------------------
\newcommand{\breakquestion}{%
  \par\nobreak
  \hfill\textit{(question continues on next page)}\par
  \newpage
  \textit{(question continued)}\par\smallskip
}

% ---------------------------------------------------------------------
% solution: model-answer block. With the `shadedsolutions` class option
% it is rendered on a light grey background; otherwise it is a plain,
% clearly-labelled paragraph.
% ---------------------------------------------------------------------
\newenvironment{solution}{%
  \ifbooklet@shaded
    \definecolor{shadecolor}{gray}{0.92}%
    \begin{shaded}%
  \fi
  \textbf{Solution:}\par\smallskip
}{%
  \ifbooklet@shaded
    \end{shaded}%
  \fi
  \vspace{0.4cm}
}

% ---------------------------------------------------------------------
% \answerspace{len}: ruled blank area of height <len> for handwritten
% working/answers directly under a question or sub-question.
% ---------------------------------------------------------------------
\newcommand{\answerspace}[1]{%
  \par\vspace{0.2cm}%
  \noindent\rule{\linewidth}{0.4pt}\par
  \vspace{#1}%
  \noindent\rule{\linewidth}{0.4pt}\par
  \vspace{0.2cm}%
}

% ---------------------------------------------------------------------
% \answerfill: blank out the remainder of the current page as answer
% space, then start the next question on a fresh page.
% ---------------------------------------------------------------------
\newcommand{\answerfill}{%
  \par\vspace*{\fill}%
  \newpage
}

\endinput
