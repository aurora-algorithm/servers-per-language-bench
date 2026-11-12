package bench.orders;

import java.lang.management.GarbageCollectorMXBean;
import java.lang.management.ManagementFactory;
import java.util.stream.Collectors;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class App {
  public static void main(String[] args) {
    // The server log keeps what the JVM chose under the core pinning: its CPU count and garbage
    // collector.
    String collectors =
        ManagementFactory.getGarbageCollectorMXBeans().stream()
            .map(GarbageCollectorMXBean::getName)
            .collect(Collectors.joining(", "));
    System.out.println(
        "java "
            + Runtime.version()
            + ", availableProcessors "
            + Runtime.getRuntime().availableProcessors()
            + ", gc "
            + collectors);
    SpringApplication.run(App.class, args);
  }
}
