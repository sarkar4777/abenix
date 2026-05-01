package com.abenix.claimsiq;

import com.vaadin.flow.component.page.AppShellConfigurator;
import com.vaadin.flow.theme.Theme;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
@Theme("claimsiq")
public class ClaimsIqApplication implements AppShellConfigurator {
    public static void main(String[] args) {
        SpringApplication.run(ClaimsIqApplication.class, args);
    }
}
