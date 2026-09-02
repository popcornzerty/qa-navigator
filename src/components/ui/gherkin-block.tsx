import { Fragment } from "react";

const KEYWORD = /^(Feature|Scenario|Scenario Outline|Background|Examples|Given|When|Then|And|But):?\s?/;

function keywordClass(keyword: string): string {
  if (keyword === "Feature" || keyword.startsWith("Scenario") || keyword === "Background")
    return "text-primary";
  if (keyword === "Given" || keyword === "Then") return "text-pass";
  return "text-skip";
}

/** Renders Gherkin text with keyword highlighting. */
export function GherkinBlock({ text }: { text: string }) {
  return (
    <pre className="overflow-x-auto px-5 py-4 font-mono text-[12.5px] leading-6 text-muted-foreground">
      {text.split("\n").map((line, index) => {
        const match = line.trim().match(KEYWORD);
        if (!match) {
          return <Fragment key={index}>{line + "\n"}</Fragment>;
        }
        const keyword = match[1]!;
        const indent = line.slice(0, line.indexOf(keyword));
        const rest = line.slice(indent.length + match[0].length);
        const isTitle = keyword === "Feature" || keyword.startsWith("Scenario");
        return (
          <Fragment key={index}>
            {indent}
            <span className={keywordClass(keyword)}>{keyword}</span>
            <span className="text-foreground/80">{isTitle ? ": " : " "}</span>
            <span className={isTitle ? "text-foreground/80" : "text-muted-foreground"}>{rest}</span>
            {"\n"}
          </Fragment>
        );
      })}
    </pre>
  );
}
