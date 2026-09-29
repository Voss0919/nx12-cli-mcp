using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using NXOpen;
using NXOpen.Features;

public class VerifyTube
{
    public static void Main(string[] args)
    {
        try
        {
            if (args == null || args.Length != 4) throw new ArgumentException("output, outer_d, bore_d, height required");
            string path = Path.GetFullPath(args[0]);
            double outer = double.Parse(args[1], CultureInfo.InvariantCulture);
            double bore = double.Parse(args[2], CultureInfo.InvariantCulture);
            double height = double.Parse(args[3], CultureInfo.InvariantCulture);
            if (!File.Exists(path)) throw new FileNotFoundException("Model missing", path);

            Session session = Session.GetSession();
            PartLoadStatus status;
            Part part = session.Parts.OpenDisplay(path, out status);
            if (part == null || (status != null && status.NumberUnloadedParts > 0)) throw new Exception("Reopen failed");
            Body[] bodies = part.Bodies.ToArray();
            Feature[] features = part.Features.ToArray();
            int suppressed = 0;
            foreach (Feature feature in features) if (feature.Suppressed) suppressed++;
            if (bodies.Length != 1 || features.Length < 2 || suppressed != 0)
                throw new Exception("Unexpected body/feature state");

            Unit area = null, volume = null, mass = null, length = null;
            foreach (Unit unit in part.UnitCollection)
            {
                if (unit.TypeName == "SquareMilliMeter") area = unit;
                if (unit.TypeName == "CubicMilliMeter") volume = unit;
                if (unit.TypeName == "Kilogram") mass = unit;
                if (unit.TypeName == "MilliMeter") length = unit;
            }
            MeasureBodies measure = part.MeasureManager.NewMassProperties(
                new Unit[] { area, volume, mass, length }, 0.9999, new IBody[] { bodies[0] });
            double actual = measure.Volume;
            double expected = Math.PI * (outer * outer - bore * bore) * height / 4;
            double error = Math.Abs(actual - expected) / expected;
            if (error > 0.005) throw new Exception("Volume error " + error.ToString(CultureInfo.InvariantCulture));
            Console.WriteLine("BODIES=" + bodies.Length);
            Console.WriteLine("FEATURES=" + features.Length);
            Console.WriteLine("SUPPRESSED=" + suppressed);
            Console.WriteLine("VOLUME_MM3=" + actual.ToString("R", CultureInfo.InvariantCulture));
            Console.WriteLine("EXPECTED_MM3=" + expected.ToString("R", CultureInfo.InvariantCulture));
            Console.WriteLine("RELATIVE_ERROR=" + error.ToString("R", CultureInfo.InvariantCulture));
            Console.WriteLine("RESULT: PASS");
        }
        catch (Exception e)
        {
            Console.WriteLine("ERROR=" + e);
            Console.WriteLine("RESULT: FAIL");
        }
    }

    public static int GetUnloadOption(string dummy) { return (int)Session.LibraryUnloadOption.Immediately; }
}
